from __future__ import annotations

import asyncio
import gc
import importlib.util
from pathlib import Path
import sys
import types
import weakref

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "dji_power_bt"
# Locally administered unicast address reserved for tests; not tied to hardware.
TEST_BLE_ADDRESS = "02:00:00:00:00:01"


def _module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


# Minimal runtime stubs: enough to import and exercise manager transport logic.
custom_components = sys.modules.setdefault(
    "custom_components", types.ModuleType("custom_components")
)
custom_components.__path__ = []
dji_pkg = sys.modules.setdefault(
    "custom_components.dji_power_bt",
    types.ModuleType("custom_components.dji_power_bt"),
)
dji_pkg.__path__ = [str(ROOT)]

bleak = _module("bleak")
bleak.BleakClient = object
bleak_exc = _module("bleak.exc")


class BleakError(Exception):
    pass


bleak_exc.BleakError = BleakError
bleak_backends = _module("bleak.backends")
bleak_device = _module("bleak.backends.device")


class BLEDevice:
    def __init__(self, address: str, name: str | None = None) -> None:
        self.address = address
        self.name = name


bleak_device.BLEDevice = BLEDevice

retry = _module("bleak_retry_connector")
retry.BleakClientWithServiceCache = object
retry.device_source = lambda _device: "test"


async def _unused(*_args, **_kwargs):
    raise AssertionError("stub should have been replaced")


retry.establish_connection = _unused
retry.close_stale_connections_by_address = _unused

ha = _module("homeassistant")
ha_components = _module("homeassistant.components")
ha_bluetooth = _module("homeassistant.components.bluetooth")
ha_bluetooth.async_scanner_count = lambda *_args, **_kwargs: 1
ha_bluetooth.async_ble_device_from_address = lambda *_args, **_kwargs: None
ha_bluetooth.async_last_service_info = lambda *_args, **_kwargs: None
ha_bluetooth.async_scanner_devices_by_address = lambda *_args, **_kwargs: []
ha_components.bluetooth = ha_bluetooth
ha_config_entries = _module("homeassistant.config_entries")
ha_config_entries.ConfigEntry = object
ha_core = _module("homeassistant.core")
ha_core.HomeAssistant = object
ha_helpers = _module("homeassistant.helpers")
ha_device_registry = _module("homeassistant.helpers.device_registry")
ha_device_registry.CONNECTION_BLUETOOTH = "bluetooth"
ha_helpers.device_registry = ha_device_registry
ha_exceptions = _module("homeassistant.exceptions")


class HomeAssistantError(Exception):
    pass


ha_exceptions.HomeAssistantError = HomeAssistantError


def load(name: str):
    fq = f"custom_components.dji_power_bt.{name}"
    if fq in sys.modules:
        return sys.modules[fq]
    spec = importlib.util.spec_from_file_location(fq, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[fq] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


load("const")
load("capabilities")
load("protocol")
load("write_policy")
manager_mod = load("manager")
manager_connection_mod = sys.modules[
    "custom_components.dji_power_bt.manager_connection"
]
manager_transport_mod = sys.modules[
    "custom_components.dji_power_bt.manager_transport"
]


class FakeEntry:
    title = "DJI Power 2000"
    data = {
        "address": TEST_BLE_ADDRESS,
        "local_auth_key": "0123456789abcdef0123456789abcdef",
        "model": "DJI Power 2000",
        "model_code": 0x94,
    }
    options: dict = {}


class FakeHass:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop


def make_manager() -> object:
    return manager_mod.DjiPowerManager(
        FakeHass(asyncio.get_running_loop()),
        FakeEntry(),
        connection_operation_lock=asyncio.Lock(),
    )


def test_establish_connection_uses_two_internal_attempts() -> None:
    async def scenario() -> None:
        captured: dict = {}

        class Client:
            is_connected = True
            address = TEST_BLE_ADDRESS

        async def fake_establish(*args, **kwargs):
            captured.update(kwargs)
            return Client()

        original = manager_connection_mod.establish_connection
        manager_connection_mod.establish_connection = fake_establish
        try:
            item = make_manager()
            await item._establish_client(BLEDevice(Client.address, "Power2000"))
        finally:
            manager_connection_mod.establish_connection = original
        assert captured["max_attempts"] == 2
        assert captured["timeout"] >= 10

    asyncio.run(scenario())


def test_request_success_response_cleans_up_future_without_name_error() -> None:
    async def scenario() -> None:
        protocol = sys.modules["custom_components.dji_power_bt.protocol"]
        item = make_manager()

        response_frame = protocol.DumlFrame(
            raw=b"",
            length=0,
            version=1,
            header_crc_ok=True,
            crc16_ok=True,
            sender=0xAB,
            receiver=0x02,
            seq=0,
            cmd_type=0x80,
            cmd_set=0x5A,
            cmd_id=0x6A,
            payload=b"\x00\x01\x02\x03\x04",
        )

        async def fake_write_frame(
            *,
            seq: int,
            cmd_type: int,
            cmd_set: int,
            cmd_id: int,
            payload: bytes,
            response: bool = True,
        ) -> bytes:
            key = (item._connection_generation, seq)
            _expected_set, _expected_id, future = item._pending[key]
            response_frame.seq = seq
            response_frame.cmd_id = cmd_id
            future.set_result(response_frame)
            return b"frame"

        item._write_frame = fake_write_frame
        result = await item._request(cmd_id=0x6A, payload=b"\x00")

        assert result is response_frame
        assert item._pending == {}

    asyncio.run(scenario())


def test_connection_health_watchdog_uses_split_module_timeout_constant() -> None:
    async def scenario() -> None:
        class Client:
            is_connected = True

        item = make_manager()
        item._client = Client()
        item.state.authenticated = True
        item._last_notify_monotonic = (
            asyncio.get_running_loop().time()
            - manager_connection_mod.NOTIFY_WATCHDOG_TIMEOUT
            - 1.0
        )

        issue = item._connection_health_issue()
        assert issue is not None
        assert issue.startswith("notify_watchdog_timeout_")

    asyncio.run(scenario())


def test_runtime_dji_advertisement_can_refresh_capabilities_after_split() -> None:
    async def scenario() -> None:
        class ServiceInfo:
            address = TEST_BLE_ADDRESS
            name = "Power1000Mini-test"
            source = "proxy-test"
            manufacturer_data = {0x08AA: b"dummy"}

        class Advertisement:
            model_code = 0x98
            model = "DJI Power 1000 Mini"
            bound = True
            mac_candidate = TEST_BLE_ADDRESS

        item = make_manager()
        original_last_service_info = ha_bluetooth.async_last_service_info
        original_parse = manager_connection_mod.parse_manufacturer_data
        ha_bluetooth.async_last_service_info = lambda *_args, **_kwargs: ServiceInfo()
        manager_connection_mod.parse_manufacturer_data = lambda _payload: Advertisement()
        try:
            item._validate_and_record_ble_device(
                BLEDevice(item.address, "Power2000"),
                resolution="ha_current",
            )
        finally:
            ha_bluetooth.async_last_service_info = original_last_service_info
            manager_connection_mod.parse_manufacturer_data = original_parse

        assert item.model_code == 0x98
        assert item.model == "DJI Power 1000 Mini"
        assert item.capabilities == manager_connection_mod.capabilities_for_model_code(0x98)
        assert item.state.identity_status == "dji_manufacturer_verified"

    asyncio.run(scenario())


def test_gatt_write_timeout_marks_transport_unhealthy_and_releases_lock() -> None:
    async def scenario() -> None:
        class HangingClient:
            is_connected = True

            async def write_gatt_char(self, *_args, **_kwargs) -> None:
                await asyncio.sleep(60)

        item = make_manager()
        item._client = HangingClient()
        item.state.connected = True
        item.state.authenticated = True

        original_timeout = manager_transport_mod.GATT_WRITE_TIMEOUT
        manager_transport_mod.GATT_WRITE_TIMEOUT = 0.01
        try:
            try:
                await item._write_frame(
                    seq=1,
                    cmd_type=0x20,
                    cmd_set=0x5A,
                    cmd_id=0x62,
                    payload=b"\x01",
                )
            except manager_mod.DjiPowerConnectionError:
                pass
            else:
                raise AssertionError("write timeout did not raise")
        finally:
            manager_transport_mod.GATT_WRITE_TIMEOUT = original_timeout

        assert item.state.gatt_write_timeout_count == 1
        assert item._transport_unhealthy_reason == "gatt_write_timeout"
        assert not item._write_lock.locked()
        assert item.write_lock_age_s is None

    asyncio.run(scenario())


def test_cancel_ack_tasks_cancels_tracked_background_ack() -> None:
    async def scenario() -> None:
        item = make_manager()
        task = asyncio.create_task(asyncio.sleep(60))
        item._ack_tasks.add(task)
        item._cancel_ack_tasks()
        await asyncio.sleep(0)
        assert task.cancelled()
        assert item.ack_task_count == 0

    asyncio.run(scenario())


def test_tariff_button_operation_skips_matching_profile_and_writes_0x1016_otherwise() -> None:
    async def scenario() -> None:
        protocol = sys.modules["custom_components.dji_power_bt.protocol"]
        item = make_manager()
        item.state.connected = True
        item.state.authenticated = True
        item.state.config = protocol.PowerConfig(
            source_cmd_id=0x60,
            source_payload=b"",
            tariff_slots=protocol.make_all_day_tariff_slots("peak"),
        )
        item._last_config_report_monotonic = asyncio.get_running_loop().time()

        async def unexpected_request(**_kwargs):
            raise AssertionError("matching tariff profile should not write")

        item._request = unexpected_request
        await item.async_set_all_day_tariff("peak")

        item.state.config.tariff_slots = []
        captured: dict = {}

        async def successful_request(*, cmd_id: int, payload: bytes, timeout: float = 10.0):
            captured["cmd_id"] = cmd_id
            captured["payload"] = payload
            ack_payload = protocol.build_keyed_header(timestamp_ms=1) + (
                (0x100E).to_bytes(2, "little")
                + (4).to_bytes(2, "little")
                + (0).to_bytes(4, "little")
                + (0x1016).to_bytes(2, "little")
                + (4).to_bytes(2, "little")
                + (0).to_bytes(4, "little")
            )
            return protocol.DumlFrame(
                raw=b"",
                length=0,
                version=1,
                header_crc_ok=True,
                crc16_ok=True,
                sender=0xAB,
                receiver=0x02,
                seq=0x1234,
                cmd_type=0x80,
                cmd_set=0x5A,
                cmd_id=0x63,
                payload=ack_payload,
            )

        item._request = successful_request
        await item.async_set_all_day_tariff("off_peak")
        item._cancel_write_verifications()

        assert captured["cmd_id"] == 0x63
        assert bytes.fromhex(
            "16 10 1c 00 "
            "16 00 0a 00 02 01 7f 00 00 00 00 00 17 3b "
            "16 00 0a 00 02 01 7f 00 00 00 17 3b 00 00"
        ) in captured["payload"]
        assert (
            protocol.classify_tariff_schedule(item.state.config.tariff_slots)
            == "all_day_off_peak"
        )
        assert item.state.last_write_property == "tariff_schedule_all_day_off_peak"

    asyncio.run(scenario())


def test_custom_tariff_action_skips_matching_full_table_regardless_of_order() -> None:
    async def scenario() -> None:
        protocol = sys.modules["custom_components.dji_power_bt.protocol"]
        item = make_manager()
        item.state.connected = True
        item.state.authenticated = True
        periods = [
            {
                "tariff": "off_peak",
                "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                "start_time": "23:00:00",
                "end_time": "07:00:00",
            },
            {
                "tariff": "peak",
                "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                "start_time": "07:00:00",
                "end_time": "23:00:00",
            },
        ]
        slots = protocol.make_tariff_slots_from_periods(periods)
        item.state.config = protocol.PowerConfig(
            source_cmd_id=0x60,
            source_payload=b"",
            tariff_slots=list(reversed(slots)),
        )
        item._last_config_report_monotonic = asyncio.get_running_loop().time()

        async def unexpected_request(**_kwargs):
            raise AssertionError("matching tariff table should not write")

        item._request = unexpected_request
        await item.async_set_tariff_schedule(periods=periods)

    asyncio.run(scenario())


def test_reconnect_preserves_previous_disconnect_diagnostics() -> None:
    async def scenario() -> None:
        class Client:
            is_connected = True
            address = TEST_BLE_ADDRESS

        item = make_manager()
        item._ever_connected = True
        item.state.last_disconnect_reason = "unexpected_disconnect"
        item.state.last_disconnect_at = "2026-08-03T09:29:30+00:00"
        item.state.last_connection_error = "TimeoutError: timeout waiting for 0x60 response"
        item.state.last_connection_error_at = "2026-08-03T09:29:31+00:00"

        item._record_connected_client(
            Client(), BLEDevice(Client.address, "Power2000")
        )

        assert item.state.connected is True
        assert item.state.reconnect_count == 1
        assert item.state.last_disconnect_reason == "unexpected_disconnect"
        assert item.state.last_disconnect_at == "2026-08-03T09:29:30+00:00"
        assert item.state.last_connection_error == (
            "TimeoutError: timeout waiting for 0x60 response"
        )
        assert item.state.last_connection_error_at == "2026-08-03T09:29:31+00:00"

    asyncio.run(scenario())


def _scheduled_1018_value(
    *,
    mode_raw: int = 2,
    peak_raw: int = 2,
    off_peak_raw: int = 2,
    power_w: int = 800,
) -> bytes:
    value = bytearray(0x56)
    value[0] = 1
    value[1] = mode_raw
    value[2] = peak_raw
    value[3] = off_peak_raw
    value[4:8] = (1300).to_bytes(4, "little")
    value[8:12] = (600).to_bytes(4, "little")
    value[12:16] = power_w.to_bytes(4, "little")
    return bytes(value)


def test_bulk_0x1018_service_writes_all_requested_fields_once_and_skips_noop() -> None:
    async def scenario() -> None:
        protocol = sys.modules["custom_components.dji_power_bt.protocol"]
        item = make_manager()
        item.state.connected = True
        item.state.authenticated = True
        item.state.config = protocol.PowerConfig(
            source_cmd_id=0x60,
            source_payload=b"",
            tlv_1018_value=_scheduled_1018_value(),
            energy_saver_raw=2,
            peak_discharge_raw=2,
            off_peak_charge_raw=2,
            off_peak_charge_power_max_w=1300,
            off_peak_charge_power_min_w=600,
            off_peak_charging_power_w=800,
        )
        item._last_config_report_monotonic = asyncio.get_running_loop().time()
        requests: list[bytes] = []

        async def successful_request(*, cmd_id: int, payload: bytes, timeout: float = 10.0):
            assert cmd_id == 0x63
            requests.append(payload)
            ack_payload = protocol.build_keyed_header(timestamp_ms=1) + (
                (0x100E).to_bytes(2, "little")
                + (4).to_bytes(2, "little")
                + (0).to_bytes(4, "little")
                + (0x1018).to_bytes(2, "little")
                + (4).to_bytes(2, "little")
                + (0).to_bytes(4, "little")
            )
            return protocol.DumlFrame(
                raw=b"",
                length=0,
                version=1,
                header_crc_ok=True,
                crc16_ok=True,
                sender=0xAB,
                receiver=0x02,
                seq=0x2345,
                cmd_type=0x80,
                cmd_set=0x5A,
                cmd_id=0x63,
                payload=ack_payload,
            )

        item._request = successful_request
        await item.async_set_scheduled_energy_settings(
            energy_optimization_mode="scheduled",
            peak_discharging=True,
            off_peak_charging=True,
            off_peak_charging_power=900,
        )

        assert len(requests) == 1
        tlv_1018 = protocol.find_first_tlv(
            requests[0], 0x1018, expected_lengths={0x56}
        )
        assert tlv_1018 is not None
        value = tlv_1018[1]
        assert value[1] == 2
        assert value[2] == 1
        assert value[3] == 1
        assert int.from_bytes(value[12:16], "little") == 900
        assert item.state.last_write_property == "scheduled_energy_settings"

        # The optimistic cache now matches the same requested state. A repeated
        # automation call must not create a second 0x63 transaction.
        await item.async_set_scheduled_energy_settings(
            energy_optimization_mode="scheduled",
            peak_discharging=True,
            off_peak_charging=True,
            off_peak_charging_power=900,
        )
        assert len(requests) == 1
        item._cancel_write_verifications()

    asyncio.run(scenario())


def test_bulk_0x1018_service_rejects_scheduled_fields_in_disabled_result_mode() -> None:
    async def scenario() -> None:
        protocol = sys.modules["custom_components.dji_power_bt.protocol"]
        item = make_manager()
        item.state.connected = True
        item.state.authenticated = True
        item.state.config = protocol.PowerConfig(
            source_cmd_id=0x60,
            source_payload=b"",
            tlv_1018_value=_scheduled_1018_value(mode_raw=1),
            energy_saver_raw=1,
            peak_discharge_raw=2,
            off_peak_charge_raw=2,
            off_peak_charge_power_max_w=1300,
            off_peak_charge_power_min_w=600,
            off_peak_charging_power_w=800,
        )
        item._last_config_report_monotonic = asyncio.get_running_loop().time()
        try:
            await item.async_set_scheduled_energy_settings(
                energy_optimization_mode="disabled",
                off_peak_charging=True,
            )
        except HomeAssistantError:
            pass
        else:
            raise AssertionError("disabled resulting mode accepted scheduled fields")

    asyncio.run(scenario())



def test_unexpected_disconnect_arms_fresh_advertisement_gate_and_retires_client() -> None:
    async def scenario() -> None:
        class Client:
            is_connected = False
            address = TEST_BLE_ADDRESS

            async def disconnect(self) -> None:
                self.disconnect_called = True

        item = make_manager()
        client = Client()
        item._client = client
        item._last_ble_device = BLEDevice(client.address, "Power2000")
        item.state.connected = True
        item.state.authenticated = True

        item._handle_disconnected_callback(client)

        assert item._client is None
        assert item._retired_client is client
        assert item.state.connected is False
        assert item.state.last_disconnect_reason == "unexpected_disconnect"
        assert item._fresh_advertisement_required is True
        assert item._last_ble_device is None
        events = [record["event"] for record in item.connection_event_history]
        assert "disconnect_callback" in events
        assert "unexpected_disconnect_reconnect_gate_armed" in events

    asyncio.run(scenario())


def test_expected_disconnect_callback_does_not_arm_reconnect_gate() -> None:
    async def scenario() -> None:
        class Client:
            is_connected = False
            address = TEST_BLE_ADDRESS

        item = make_manager()
        client = Client()
        item._client = client
        item._expected_disconnect_client_ids[id(client)] = (
            weakref.ref(client),
            asyncio.get_running_loop().time(),
        )

        item._handle_disconnected_callback(client)

        assert item._client is None
        assert item._retired_client is None
        assert item._fresh_advertisement_required is False
        record = item.connection_event_history[-1]
        assert record["event"] == "disconnect_callback"
        assert record["expected_disconnect"] is True

    asyncio.run(scenario())


def test_expected_disconnect_tracking_does_not_own_client() -> None:
    async def scenario() -> None:
        class Client:
            address = TEST_BLE_ADDRESS

            def __init__(self) -> None:
                self.is_connected = True

            async def disconnect(self) -> None:
                self.is_connected = False

        item = make_manager()
        client = Client()
        client_id = id(client)
        client_ref = weakref.ref(client)

        await item._disconnect_client(
            client,
            stop_notify=False,
            force=True,
            context="weakref_regression",
            expected=True,
        )

        tracked_ref, _timestamp = item._expected_disconnect_client_ids[client_id]
        assert isinstance(tracked_ref, weakref.ReferenceType)
        assert tracked_ref() is client

        # No active/retired/backend owner remains in this regression fixture.
        # The expected-callback bookkeeping itself must therefore not keep the
        # client alive if the callback never arrives.
        client = None
        gc.collect()

        assert client_ref() is None
        assert tracked_ref() is None
        assert item.client_lifecycle_diagnostics[
            "expected_disconnect_client_count"
        ] == 0
        assert item._expected_disconnect_client_ids == {}

    asyncio.run(scenario())


def test_unexpected_reconnect_cleans_retired_client_and_waits_for_fresh_advertisement() -> None:
    async def scenario() -> None:
        class Client:
            is_connected = False
            address = TEST_BLE_ADDRESS
            disconnect_called = False

            async def disconnect(self) -> None:
                self.disconnect_called = True

        class ServiceInfo:
            address = TEST_BLE_ADDRESS
            name = "Power2000"
            source = "proxy"
            manufacturer_data = {}
            device = BLEDevice(address, name)

        class Mode:
            PASSIVE = "passive"

        item = make_manager()
        retired = Client()
        item._retired_client = retired
        item._fresh_advertisement_required = True
        item._unexpected_disconnect_monotonic = asyncio.get_running_loop().time()

        clear_calls: list[str] = []
        process_calls: list[dict] = []

        def clear_history(_hass, address: str) -> None:
            clear_calls.append(address)

        async def process_advertisements(
            _hass, matcher, match_dict, mode, timeout
        ):
            process_calls.append(
                {"match": match_dict, "mode": mode, "timeout": timeout}
            )
            info = ServiceInfo()
            assert matcher(info)
            return info

        original_clear = getattr(
            ha_bluetooth, "async_clear_advertisement_history", None
        )
        original_process = getattr(
            ha_bluetooth, "async_process_advertisements", None
        )
        original_mode = getattr(ha_bluetooth, "BluetoothScanningMode", None)
        original_settle = manager_connection_mod.UNEXPECTED_DISCONNECT_SETTLE_SECONDS
        ha_bluetooth.async_clear_advertisement_history = clear_history
        ha_bluetooth.async_process_advertisements = process_advertisements
        ha_bluetooth.BluetoothScanningMode = Mode
        manager_connection_mod.UNEXPECTED_DISCONNECT_SETTLE_SECONDS = 0.0
        try:
            device = await item._resolve_device_for_connection(7)
        finally:
            manager_connection_mod.UNEXPECTED_DISCONNECT_SETTLE_SECONDS = original_settle
            if original_clear is None:
                delattr(ha_bluetooth, "async_clear_advertisement_history")
            else:
                ha_bluetooth.async_clear_advertisement_history = original_clear
            if original_process is None:
                delattr(ha_bluetooth, "async_process_advertisements")
            else:
                ha_bluetooth.async_process_advertisements = original_process
            if original_mode is None:
                delattr(ha_bluetooth, "BluetoothScanningMode")
            else:
                ha_bluetooth.BluetoothScanningMode = original_mode

        assert retired.disconnect_called is True
        assert item._retired_client is None
        assert item._expected_disconnect_client_ids == {}
        assert device.address == item.address
        assert clear_calls == [item.address]
        assert process_calls[0]["match"] == {
            "address": item.address,
            "connectable": True,
        }
        assert item._fresh_advertisement_required is False
        assert item._fresh_advertisement_received_at is not None
        events = [record["event"] for record in item.connection_event_history]
        assert "disconnect_requested" in events
        assert "fresh_advertisement_wait_start" in events
        assert "fresh_advertisement_received" in events

    asyncio.run(scenario())


def test_manual_disconnect_does_not_leave_retired_client_expected_callback() -> None:
    async def scenario() -> None:
        class Client:
            is_connected = False
            address = TEST_BLE_ADDRESS
            disconnect_called = False

            async def disconnect(self) -> None:
                self.disconnect_called = True

        item = make_manager()
        retired = Client()
        item._retired_client = retired
        item._fresh_advertisement_required = True

        await item.async_disconnect(reason="manual_disable")

        assert retired.disconnect_called is True
        assert item._retired_client is None
        assert item._expected_disconnect_client_ids == {}
        assert item._fresh_advertisement_required is False

        retired_requests = [
            record
            for record in item.connection_event_history
            if record["event"] == "disconnect_requested"
            and record.get("disconnect_context") == "manual_disable:retired_client"
        ]
        assert len(retired_requests) == 1
        assert retired_requests[0]["expected_disconnect"] is False

    asyncio.run(scenario())


def test_connection_events_are_shared_across_managers() -> None:
    async def scenario() -> None:
        class Runtime:
            def __init__(self) -> None:
                self.connection_operation_lock = asyncio.Lock()
                self.connection_event_history: list[dict] = []
                self.connection_lock_holder = None
                self.connection_lock_waiters = 0
                self.next_event = 1
                self.next_attempt = 1

            def next_connection_attempt_id(self) -> int:
                value = self.next_attempt
                self.next_attempt += 1
                return value

            def record_connection_event(self, event: dict) -> int:
                value = self.next_event
                self.next_event += 1
                record = dict(event)
                record["event_id"] = value
                self.connection_event_history.append(record)
                return value

        runtime = Runtime()
        first = manager_mod.DjiPowerManager(
            FakeHass(asyncio.get_running_loop()),
            FakeEntry(),
            connection_operation_lock=runtime.connection_operation_lock,
            domain_runtime=runtime,
        )

        class MiniEntry(FakeEntry):
            entry_id = "mini"
            title = "DJI Power 1000 Mini"
            data = dict(FakeEntry.data, model="DJI Power 1000 Mini", model_code=0x98)

        second = manager_mod.DjiPowerManager(
            FakeHass(asyncio.get_running_loop()),
            MiniEntry(),
            connection_operation_lock=runtime.connection_operation_lock,
            domain_runtime=runtime,
        )
        first._record_connection_event("first")
        second._record_connection_event("second")

        assert [item["event"] for item in runtime.connection_event_history] == [
            "first",
            "second",
        ]
        assert first.connection_event_history[-1]["event_id"] == 1
        assert second.connection_event_history[-1]["event_id"] == 2

    asyncio.run(scenario())


def test_connect_error_preserves_unexpected_disconnect_fresh_gate() -> None:
    async def scenario() -> None:
        item = make_manager()
        item._fresh_advertisement_required = True
        item._unexpected_disconnect_monotonic = asyncio.get_running_loop().time()

        await item.async_disconnect(reason="connect_error")

        assert item._fresh_advertisement_required is True
        assert item._unexpected_disconnect_monotonic is not None

    asyncio.run(scenario())


def test_connection_exception_categories_are_diagnostic_friendly() -> None:
    assert (
        manager_mod._classify_connection_exception(
            RuntimeError("No connection slots available")
        )
        == "out_of_slots"
    )
    assert (
        manager_mod._classify_connection_exception(
            RuntimeError("out of connection slots")
        )
        == "out_of_slots"
    )
    assert manager_mod._classify_connection_exception(TimeoutError()) == "timeout"
    assert (
        manager_mod._classify_connection_exception(
            manager_mod.DjiPowerConnectionError("not reachable")
        )
        == "device_not_found"
    )


def test_connect_error_during_fresh_gate_preserves_original_disconnect_reason() -> None:
    async def scenario() -> None:
        item = make_manager()
        item.state.last_disconnect_reason = "unexpected_disconnect"
        item.state.last_disconnect_at = "2026-08-05T08:00:00+00:00"
        item._fresh_advertisement_required = True
        item._unexpected_disconnect_monotonic = asyncio.get_running_loop().time()

        await item.async_disconnect(reason="connect_error")

        assert item.state.last_disconnect_reason == "unexpected_disconnect"
        assert item.state.last_disconnect_at == "2026-08-05T08:00:00+00:00"

    asyncio.run(scenario())


def test_connection_exception_category_follows_wrapped_timeout_cause() -> None:
    try:
        try:
            raise TimeoutError("advertisement wait")
        except TimeoutError as exc:
            raise manager_mod.DjiPowerConnectionError("fresh advertisement missing") from exc
    except manager_mod.DjiPowerConnectionError as wrapped:
        assert manager_mod._classify_connection_exception(wrapped) == "timeout"


def test_device_registry_firmware_sync_is_model_independent() -> None:
    async def scenario() -> None:
        class Device:
            id = "device-id"

            def __init__(self) -> None:
                self.sw_version = None

        class Registry:
            def __init__(self) -> None:
                self.device = Device()
                self.lookups: list[set[tuple[str, str]]] = []
                self.updates: list[tuple[str, str]] = []

            def async_get_device(self, *, identifiers):
                self.lookups.append(identifiers)
                return self.device

            def async_update_device(self, device_id: str, *, sw_version: str):
                self.updates.append((device_id, sw_version))
                self.device.sw_version = sw_version
                return self.device

        registry = Registry()
        original_async_get = getattr(manager_mod.dr, "async_get", None)
        manager_mod.dr.async_get = lambda _hass: registry
        try:
            power_2000 = make_manager()
            power_2000.state.config = manager_mod.PowerConfig(
                source_cmd_id=0x60, source_payload=b"", firmware="01.00.1500"
            )
            power_2000._sync_device_registry_firmware()

            class MiniEntry(FakeEntry):
                title = "DJI Power 1000 Mini"
                data = dict(
                    FakeEntry.data,
                    model="DJI Power 1000 Mini",
                    model_code=0x98,
                )

            registry.device.sw_version = None
            power_1000_mini = manager_mod.DjiPowerManager(
                FakeHass(asyncio.get_running_loop()),
                MiniEntry(),
                connection_operation_lock=asyncio.Lock(),
            )
            power_1000_mini.state.config = manager_mod.PowerConfig(
                source_cmd_id=0x60, source_payload=b"", firmware="01.00.0300"
            )
            power_1000_mini._sync_device_registry_firmware()
        finally:
            if original_async_get is None:
                delattr(manager_mod.dr, "async_get")
            else:
                manager_mod.dr.async_get = original_async_get

        assert registry.lookups == [
            {("dji_power_bt", TEST_BLE_ADDRESS)},
            {("dji_power_bt", TEST_BLE_ADDRESS)},
        ]
        assert registry.updates == [
            ("device-id", "01.00.1500"),
            ("device-id", "01.00.0300"),
        ]

    asyncio.run(scenario())


def test_connection_setup_abort_after_unexpected_disconnect_does_not_leak_expected_clients() -> None:
    async def scenario() -> None:
        class Client:
            address = TEST_BLE_ADDRESS

            def __init__(self) -> None:
                self.is_connected = True
                self.disconnect_called = False

            async def disconnect(self) -> None:
                self.disconnect_called = True
                self.is_connected = False

        item = make_manager()

        # Mirrors the field diagnostic: seven reconnect clients reached setup,
        # delivered an unexpected disconnect callback, then setup-abort cleanup ran.
        for _ in range(7):
            client = Client()
            item._client = client
            item.state.connected = True
            item.state.authenticated = True
            item.state.connection_phase = "initial_config"

            client.is_connected = False
            item._handle_disconnected_callback(client)

            assert item._client is None
            assert item._retired_client is client
            assert item._expected_disconnect_client_ids == {}

            await item._abort_connection_setup(client)

            assert client.disconnect_called is True
            assert item._client is None
            assert item._retired_client is None
            assert item._expected_disconnect_client_ids == {}

        abort_requests = [
            record
            for record in item.connection_event_history
            if record["event"] == "disconnect_requested"
            and record.get("disconnect_context") == "connection_setup_abort"
        ]
        assert len(abort_requests) == 7
        assert all(record["expected_disconnect"] is False for record in abort_requests)

    asyncio.run(scenario())


def test_connection_setup_abort_still_expects_callback_for_live_client() -> None:
    async def scenario() -> None:
        item = make_manager()

        class Client:
            address = TEST_BLE_ADDRESS

            def __init__(self) -> None:
                self.is_connected = True

            async def stop_notify(self, *_args, **_kwargs) -> None:
                return None

            async def disconnect(self) -> None:
                self.is_connected = False
                item._handle_disconnected_callback(self)

        client = Client()
        item._client = client
        item.state.connected = True
        item.state.authenticated = True
        item.state.connection_phase = "initial_config"

        await item._abort_connection_setup(client)

        assert item._expected_disconnect_client_ids == {}
        assert item._retired_client is None
        abort_requests = [
            record
            for record in item.connection_event_history
            if record["event"] == "disconnect_requested"
            and record.get("disconnect_context") == "connection_setup_abort"
        ]
        assert len(abort_requests) == 1
        assert abort_requests[0]["expected_disconnect"] is True
        callbacks = [
            record
            for record in item.connection_event_history
            if record["event"] == "disconnect_callback"
        ]
        assert callbacks[-1]["expected_disconnect"] is True

    asyncio.run(scenario())


def test_connection_counters_distinguish_gatt_adoption_from_ready_reconnect() -> None:
    async def scenario() -> None:
        class Client:
            is_connected = True
            address = TEST_BLE_ADDRESS

        item = make_manager()
        device = BLEDevice(Client.address, "Power2000")

        item._record_connected_client(Client(), device)
        assert item.state.gatt_connect_count == 1
        assert item.state.gatt_reconnect_count == 0
        assert item.state.successful_reconnect_count == 0
        assert item.state.last_gatt_connect_at is not None
        assert item.state.last_ready_at is None

        item._mark_connection_ready()
        assert item.state.successful_reconnect_count == 0
        assert item.state.last_ready_at is not None

        item._record_connected_client(Client(), device)
        assert item.state.gatt_connect_count == 2
        assert item.state.gatt_reconnect_count == 1
        # A GATT adoption is not a successful reconnect until init reaches ready.
        assert item.state.successful_reconnect_count == 0

        item._mark_connection_ready()
        assert item.state.successful_reconnect_count == 1
        assert item.state.reconnect_count == item.state.gatt_reconnect_count == 1
        assert item.state.last_connect_at == item.state.last_gatt_connect_at

    asyncio.run(scenario())


def test_repeated_0x66_body_uses_structural_fast_path_and_preserves_latest_timestamp() -> None:
    async def scenario() -> None:
        protocol = sys.modules["custom_components.dji_power_bt.protocol"]
        item = make_manager()
        body = b"\x00\x00\x00\x00"
        first = protocol.build_keyed_header(timestamp_ms=1000) + body
        second = protocol.build_keyed_header(timestamp_ms=2000) + body

        item._record_safe_payload(
            direction="rx", seq=1, cmd_type=0x40, cmd_set=0x5A, cmd_id=0x66,
            payload=first,
        )
        item._record_safe_payload(
            direction="rx", seq=2, cmd_type=0x40, cmd_set=0x5A, cmd_id=0x66,
            payload=second,
        )

        assert item._hms_full_parse_count == 1
        assert item._hms_fast_path_hit_count == 1
        assert item.state.latest_hms_report is not None
        assert item.state.latest_hms_report.timestamp_ms == 2000
        assert item.state.latest_hms_report.parse_status == "empty"
        assert len(item._hms_pattern_history) == 1
        assert item._hms_pattern_history[0]["occurrence_count"] == 2
        assert item.hms_diagnostics["full_parse_count"] == 1
        assert item.hms_diagnostics["fast_path_hit_count"] == 1

        changed = protocol.build_keyed_header(timestamp_ms=3000) + b"\x01\x00\x00\x00"
        item._record_safe_payload(
            direction="rx", seq=3, cmd_type=0x40, cmd_set=0x5A, cmd_id=0x66,
            payload=changed,
        )
        assert item._hms_full_parse_count == 2
        assert item._hms_fast_path_hit_count == 1
        assert item.state.latest_hms_report is not None
        assert item.state.latest_hms_report.timestamp_ms == 3000
        assert len(item._hms_pattern_history) == 2

    asyncio.run(scenario())


def test_manager_diagnostics_snapshot_uses_precise_connection_semantics_and_shared_tuning() -> None:
    async def scenario() -> None:
        diagnostics_mod = load("manager_diagnostics")
        constants_mod = load("manager_constants")
        item = make_manager()
        item.state.last_gatt_connect_at = "2026-08-12T00:00:01+00:00"
        item.state.last_ready_at = "2026-08-12T00:00:02+00:00"
        item.state.gatt_connect_count = 4
        item.state.gatt_reconnect_count = 3
        item.state.successful_reconnect_count = 2

        snapshot = diagnostics_mod.manager_runtime_snapshot(item)

        assert snapshot["last_gatt_connect_at"] == item.state.last_gatt_connect_at
        assert snapshot["last_ready_at"] == item.state.last_ready_at
        assert snapshot["gatt_connect_count"] == 4
        assert snapshot["gatt_reconnect_count"] == 3
        assert snapshot["successful_reconnect_count"] == 2
        assert snapshot["last_connect_at"] == item.state.last_gatt_connect_at
        assert snapshot["reconnect_count"] == 3
        assert snapshot["connection_counters"] == {
            "scope": "manager_runtime_since_setup",
            "gatt_connect_count": 4,
            "gatt_reconnect_count": 3,
            "successful_reconnect_count": 2,
        }
        assert (
            snapshot["runtime_tuning"]["gatt_write_timeout_s"]
            == constants_mod.GATT_WRITE_TIMEOUT
        )
        assert (
            snapshot["runtime_tuning"]["config_cache_max_age_s"]
            == constants_mod.CONFIG_CACHE_MAX_AGE_SECONDS
        )

    asyncio.run(scenario())
