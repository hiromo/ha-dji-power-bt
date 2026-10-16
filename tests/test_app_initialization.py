"""Synthetic wire/lifecycle coverage of the observed DJI Home startup order."""
import asyncio
from unittest.mock import AsyncMock

import pytest
import test_manager_v070 as base
from test_ble_reliability import Client, tlv

protocol = base.load("protocol")
APP_GET = bytes.fromhex(
    "00001002100310051006100710081009100a100b100c100d100e101510161018101910"
    "1b101c101d101e10201021102210231024102510261027102810"
)


def wire(command, payload, seq, kind=0x80):
    return protocol.build_duml_frame(sender=0xAB, receiver=0x02, seq=seq,
                                    cmd_type=kind, cmd_set=0x5A,
                                    cmd_id=command, payload=payload)


class Station(Client):
    def __init__(self, item, *, report=True, ack_error=False, ack_block=False,
                 fail_get=None, auth_failure=False):
        super().__init__()
        self.item = item
        self.report = report
        self.ack_error = ack_error
        self.ack_block = ack_block
        self.fail_get = fail_get
        self.auth_failure = auth_failure
        self.sent = []
        self.sessions = 0
        self.gets = 0
        self.ack_started = asyncio.Event()
        self.release_ack = asyncio.Event()
        self.write_gatt_char = self.write

    async def write(self, uuid, raw, response):
        assert response is True
        f = protocol.parse_duml_frame(raw)
        assert f.header_crc_ok and f.crc16_ok
        self.sent.append(f)
        if f.cmd_id == 0x6A:
            if f.payload == b"\0":
                self.sessions += 1
                payload = b"\0" + bytes([self.sessions]) * 4
            else:
                assert self.sessions == 2
                assert f.payload[1:5] == b"\x02" * 4
                payload = b"\x01" if self.auth_failure else b"\0"
            data = wire(0x6A, payload, f.seq)
            if len(f.payload) > 1 and self.report:
                # Deliberately coalesce auth reply/report before coroutine resumes.
                data += wire(0x62, tlv(0x1005, bytes(24)), 500, 0x40)
            self.callback(None, bytearray(data))
        elif f.cmd_id == 0x62:
            self.ack_started.set()
            if self.ack_block:
                await self.release_ack.wait()
            if self.ack_error:
                raise base.BleakError("synthetic ACK failure")
        elif f.cmd_id == 0x60:
            self.gets += 1
            if self.fail_get == self.gets:
                self.is_connected = False
                self.item._handle_disconnected_callback(self)
                return
            payload = (tlv(0x1005, bytes(24)) if len(f.payload) > 3
                       else tlv(int.from_bytes(f.payload[1:], "little"), b""))
            self.callback(None, bytearray(wire(0x60, payload, f.seq)))


def prepare(item, station):
    item._resolve_device_for_connection = AsyncMock(
        return_value=base.BLEDevice(item.address, "Test"))
    item._maybe_cleanup_stale_connections = AsyncMock()
    item._establish_client = AsyncMock(return_value=station)


def test_observed_get_bytes():
    assert len(APP_GET) == 61
    assert protocol.DEFAULT_STATUS_REQUEST_PAYLOAD == APP_GET
    frame = protocol.parse_duml_frame(protocol.build_duml_frame(
        seq=10029, cmd_set=0x5A, cmd_id=0x60, payload=APP_GET))
    assert frame.length == 74 and frame.header_crc_ok and frame.crc16_ok


@pytest.mark.parametrize("model", [0x91, 0x94, 0x97, 0x98, 0xFF])
@pytest.mark.parametrize("report", [False, True])
def test_startup_without_report_barrier_and_reconnect(model, report):
    async def scenario():
        item = base.make_manager()
        item.model_code = model
        for attempt in range(2):
            station = Station(item, report=report)
            prepare(item, station)
            await item._connect_auth_and_init()
            await asyncio.sleep(0)
            assert [f.cmd_id for f in station.sent if f.cmd_id != 0x62] == [0x6A]*3 + [0x60]*5
            assert [f.payload for f in station.sent if f.cmd_id == 0x60] == [
                APP_GET, b"\0\x01\x10", b"\0\x01\x10",
                b"\0\x04\x10", b"\0\x04\x10"]
            assert sum(f.cmd_id == 0x62 for f in station.sent) == int(report)
            assert item.is_ready
            assert item.state.config.tlv_1005_value == bytes(24)
            assert item.state.config_read_request_count == 5 * (attempt + 1)
            assert all("6a" not in k.lower() for k in item._latest_payloads)
            await item.async_disconnect(reason="test")
            assert not item.is_ready
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["auth", 1, 2, 3, 4, 5])
def test_failed_startup_never_ready_and_cleans_up(failure):
    async def scenario():
        item = base.make_manager()
        station = Station(item, report=False, auth_failure=failure == "auth", fail_get=failure)
        prepare(item, station)
        updates = []
        item.async_add_listener(lambda: updates.append(item.is_ready))
        with pytest.raises((base.manager_mod.DjiPowerConnectionError, base.manager_mod.DjiPowerAuthError)):
            await item._connect_auth_and_init()
        assert not item.state.connected and not item.state.authenticated
        assert not item._pending and not item._ack_tasks and item._client is None
        assert not item._ever_ready and not any(updates)
        assert item.state.last_connection_failure_phase == (
            "authenticating" if failure == "auth" else "initial_config")
    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["complete", "disconnect", "cancel"])
def test_initialization_buffers_reports_blocks_controls_and_keeps_ack(action):
    async def scenario():
        item = base.make_manager()
        station = Station(item, report=False)
        prepare(item, station)
        reached = asyncio.Event()
        release = asyncio.Event()
        original = station.write_gatt_char
        async def blocked_write(uuid, raw, response):
            f = protocol.parse_duml_frame(raw)
            if f.cmd_id == 0x60 and station.gets == 4:
                reached.set()
                await release.wait()
            await original(uuid, raw, response)
        station.write_gatt_char = blocked_write
        updates = []
        item.async_add_listener(lambda: updates.append((item.is_ready, item.state.metrics, item.state.config)))
        task = asyncio.create_task(item._connect_auth_and_init())
        await asyncio.wait_for(reached.wait(), 1)
        assert item.state.authenticated and not item.is_ready
        updates.clear()  # Initial connection-status notification remains allowed.
        station.callback(None, bytearray(wire(0x61, b"", 900, 0x40)))
        station.callback(None, bytearray(wire(0x62, tlv(0x1005, bytes(24)), 901, 0x40)))
        assert item.state.last_0x61_at and item.state.config is not None
        assert not updates and item._telemetry_publish_timer is None
        # Direct manager calls are the same boundary used by HA services.
        for call in (lambda: item.async_set_charge_limit(80),
                     lambda: item.async_set_scheduled_energy_settings(off_peak_charging_power=800),
                     lambda: item.async_set_tariff_schedule(preset="all_day_peak")):
            with pytest.raises(base.HomeAssistantError, match="initialization"):
                await call()
        assert not any(f.cmd_id == 0x63 for f in station.sent)
        if action == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif action == "disconnect":
            station.is_connected = False
            item._handle_disconnected_callback(station)
            release.set()
            with pytest.raises(base.manager_mod.DjiPowerConnectionError):
                await task
            assert updates and not any(u[0] for u in updates)
        else:
            release.set()
            await task
            await asyncio.sleep(0)
            assert len(updates) == 1 and updates[0][0]
            assert updates[0][1] is item.state.metrics and updates[0][2] is item.state.config
            assert any(f.cmd_id == 0x62 and f.seq == 901 for f in station.sent)
            await item._ensure_ready()
        assert not item._pending
        item._cancel_ack_tasks()
        item._cancel_telemetry_publish()
    asyncio.run(scenario())


def test_entity_publication_boundary_and_diagnostic_exceptions(monkeypatch):
    import importlib.util
    import sys
    import types
    class Constants:
        def __getattr__(self, key):
            return key
    class Entity:
        pass
    def module(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, m)
    module("homeassistant.helpers.entity", Entity=Entity, EntityCategory=Constants())
    module("homeassistant.const", PERCENTAGE="%", UnitOfPower=Constants(),
           UnitOfTemperature=Constants(), UnitOfTime=Constants())
    module("homeassistant.helpers.event", async_track_point_in_time=lambda *a: lambda: None)
    monkeypatch.setattr(base.ha_core, "callback", lambda f: f, raising=False)
    for name, attrs in {
        "sensor": {"SensorEntity": type("SensorEntity", (Entity,), {}), "SensorDeviceClass": Constants(), "SensorStateClass": Constants()},
        "number": {"NumberEntity": type("NumberEntity", (Entity,), {}), "NumberDeviceClass": Constants(), "NumberMode": Constants()},
        "select": {"SelectEntity": type("SelectEntity", (Entity,), {})},
        "switch": {"SwitchEntity": type("SwitchEntity", (Entity,), {}), "SwitchDeviceClass": Constants()},
        "binary_sensor": {"BinarySensorEntity": type("BinarySensorEntity", (Entity,), {}), "BinarySensorDeviceClass": Constants()},
    }.items():
        module("homeassistant.components." + name, **attrs)
    def load(name):
        fq = "custom_components.dji_power_bt." + name
        spec = importlib.util.spec_from_file_location(fq, base.ROOT / (name + ".py"))
        m = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, fq, m)
        spec.loader.exec_module(m)
        return m
    load("entity")
    sensor, number, select, switch, binary = [load(n) for n in ("sensor", "number", "select", "switch", "binary_sensor")]
    async def scenario():
        from test_ble_reliability import config
        item = base.make_manager()
        item.state.connected = item.state.authenticated = True
        item.state.connection_phase = "initial_config"
        item._apply_config(config(), source="0x62")
        s = sensor.DjiPowerSensor(item, sensor.SensorDescription(
            key="test", name="Test", value_fn=lambda m: 42,
            available_fn=lambda m: True, attrs_fn=lambda m: {"partial": 42}))
        n = number.DjiPowerNumber(item, number.NUMBERS[0])
        sel = select.DjiPowerSelect(item, select.SELECTS[0])
        switches = [switch.DjiPowerSwitch(item, d) for d in switch.SWITCHES]
        ordinary = [s, n, sel] + [e for e in switches if not e.description.available_when_disconnected]
        for e in ordinary:
            assert not e.available
            assert not e.extra_state_attributes
        assert s.native_value is None and n.native_value is None
        assert sel.options == [] and sel.current_option is None
        assert all(e.available for e in switches if e.description.available_when_disconnected)
        diagnostic = binary.DjiPowerBleConnectedBinarySensor(item)
        assert diagnostic.available and diagnostic.is_on
        item.state.connection_phase = "ready"
        assert s.available and s.native_value == 42
        assert s.extra_state_attributes == {"partial": 42}
        assert n.native_value is not None and sel.options
        item.state.connected = item.state.authenticated = False
        assert not s.available and diagnostic.available and not diagnostic.is_on
    asyncio.run(scenario())


@pytest.mark.parametrize("ack_error", [False, True])
def test_ack_runs_during_initialization_without_enabling_settings(ack_error):
    async def scenario():
        item = base.make_manager()
        station = Station(item, report=False, ack_error=ack_error)
        prepare(item, station)
        entered = asyncio.Event()
        release = asyncio.Event()
        reads = item._read_initial_config
        async def paused_reads():
            entered.set()
            await release.wait()
            return await reads()
        item._read_initial_config = paused_reads
        task = asyncio.create_task(item._connect_auth_and_init())
        await asyncio.wait_for(entered.wait(), 1)
        station.callback(None, bytearray(wire(0x62, tlv(0x1005, bytes(24)), 902, 0x40)))
        await asyncio.wait_for(station.ack_started.wait(), 1)
        assert not item.is_ready and station.gets == 0
        assert any(f.cmd_id == 0x62 and f.seq == 902 and f.payload == b"\x01" for f in station.sent)
        with pytest.raises(base.HomeAssistantError, match="initialization"):
            await item.async_set_charge_limit(80)
        release.set()
        await task
        assert item.is_ready
    asyncio.run(scenario())
