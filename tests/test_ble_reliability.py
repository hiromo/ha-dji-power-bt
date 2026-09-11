"""Behavior regressions from the September 2026 long-session audit."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import test_manager_v070 as base

protocol = base.load("protocol")


def tlv(key: int, value: bytes) -> bytes:
    return key.to_bytes(2, "little") + len(value).to_bytes(2, "little") + value


def config():
    limits = b"".join(n.to_bytes(4, "little") for n in (100, 50, 90, 50, 0, 10))
    output = tlv(0x1014, bytes((2, 1, 2))) + tlv(0x1014, bytes((5, 1, 1)))
    modes = tlv(0x101F, b"\x01" + (500).to_bytes(4, "little") + b"\x01")
    modes += tlv(0x101F, b"\x02" + (1000).to_bytes(4, "little") + b"\x02")
    return protocol.parse_power_config(
        tlv(0x1018, base._scheduled_1018_value()) + tlv(0x1005, limits)
        + tlv(0x100D, output) + tlv(0x101E, modes), source_cmd_id=0x62,
    )


def ready_manager():
    item = base.make_manager()
    item.state.connected = item.state.authenticated = True
    item._apply_config(config(), source="0x62", notify=False)
    return item


def response(command: int, payload: bytes, seq: int = 1):
    return protocol.parse_duml_frame(protocol.build_duml_frame(
        sender=0xAB, receiver=0x02, seq=seq, cmd_type=0x80,
        cmd_set=0x5A, cmd_id=command, payload=payload,
    ))


@pytest.mark.parametrize("method,current,changed,key", [
    ("async_set_off_peak_power", 800, 900, 0x1018),
    ("async_set_charge_limit", 90, 95, 0x1005),
    ("async_set_discharge_limit", 10, 15, 0x1005),
    ("async_set_off_peak_charge_enabled", False, True, 0x1018),
    ("async_set_peak_discharge_enabled", False, True, 0x1018),
    ("async_set_energy_optimization_mode", "scheduled", "disabled", 0x1018),
    ("async_set_ac_output_enabled", False, True, 0x100D),
    ("async_set_sdc_enabled", True, False, 0x100D),
    ("async_set_charging_mode", "slow", "fast", 0x101E),
])
def test_setters_coalesce_duplicates_and_preserve_verification(method, current, changed, key):
    async def scenario():
        item = ready_manager()
        request = AsyncMock(return_value=response(
            0x63, protocol.build_keyed_header(timestamp_ms=1) + tlv(key, bytes(4))
        ))
        item._request = request
        setter = getattr(item, method)
        await setter(current)
        request.assert_not_awaited()
        await setter(changed)
        assert request.await_count == 1
        assert item.state.write_verification_pending
        assert item.state.reflection_confirmed is None
        await setter(changed)
        assert request.await_count == 1
        assert item.state.write_verification_pending  # Coalescing is not confirmation.
        pending = next(iter(item._pending_verifications.values()))
        task = item._verification_tasks[pending.key]
        item._finish_write_verification(pending, confirmed=None, source="test_expired")
        task.cancel()
        await setter(changed)  # An expired optimistic value cannot suppress retries.
        assert request.await_count == 2
        # A subsequent real device report can now confirm and suppress the target.
        item._apply_config(deepcopy(item.state.config), source="0x62", notify=False)
        await setter(changed)
        assert request.await_count == 2
        item._cancel_write_verifications()
    asyncio.run(scenario())


def test_noop_uses_refreshed_state_and_does_not_bypass_validation():
    async def scenario():
        item = ready_manager()
        item._last_config_report_monotonic = None
        refreshed = config()
        refreshed.tlv_1018_value = base._scheduled_1018_value(power_w=900)
        refreshed.off_peak_charging_power_w = 900
        item._read_current_config = AsyncMock(return_value=refreshed)
        item._send_0x63_and_apply = AsyncMock()
        await item.async_set_off_peak_power(900)
        item._read_current_config.assert_awaited_once()
        item._send_0x63_and_apply.assert_not_awaited()
        with pytest.raises(ValueError):
            await item.async_set_off_peak_power(901)
        # An incomplete output table must still fail even if the target matches.
        item.state.config = protocol.parse_power_config(
            tlv(0x100D, tlv(0x1014, b"\x02\x01\x02") + b"\xff"), source_cmd_id=0x62
        )
        with pytest.raises(ValueError):
            await item.async_set_ac_output_enabled(False)
        item._send_0x63_and_apply.assert_not_awaited()
    asyncio.run(scenario())


def test_failed_ack_does_not_coalesce_retry_or_change_config():
    async def scenario():
        item = ready_manager()
        before = item.state.config.tlv_1018_value
        item._request = AsyncMock(return_value=response(
            0x63, protocol.build_keyed_header(timestamp_ms=1) + tlv(0x1018, b"\x01\x00\x00\x00")
        ))
        for _ in range(2):
            with pytest.raises(base.HomeAssistantError):
                await item.async_set_off_peak_power(900)
        assert item._request.await_count == 2
        assert item.state.config.tlv_1018_value == before
        assert not item._unconfirmed_config_writes
    asyncio.run(scenario())


@pytest.mark.parametrize("allow_readback", [False, True])
def test_real_verification_expiry_and_readback_allow_retry(allow_readback):
    async def scenario():
        item = ready_manager()
        item._request = AsyncMock(return_value=response(
            0x63, protocol.build_keyed_header(timestamp_ms=1) + tlv(0x1018, bytes(4))
        ))
        item._read_current_config = AsyncMock(return_value=config())
        await item.async_set_off_peak_power(900)
        pending = next(iter(item._pending_verifications.values()))
        pending.policy = base.load("write_policy").WriteVerificationPolicy(
            allow_readback=allow_readback, wait_for_report_s=0,
            timeout_source="test_passive_timeout",
        )
        await item._verification_tasks[pending.key]
        assert not item._pending_verifications
        assert item._read_current_config.await_count == int(allow_readback)
        assert item.state.reflection_confirmed is (False if allow_readback else None)
        await item.async_set_off_peak_power(900)
        assert item._request.await_count == 2
        item._cancel_write_verifications()
    asyncio.run(scenario())


class Client:
    address = base.TEST_BLE_ADDRESS

    def __init__(self):
        self.is_connected = True
        self.callback = None
        self.write_gatt_char = AsyncMock()

    async def start_notify(self, _uuid, callback):
        self.callback = callback

    async def stop_notify(self, _uuid):
        pass

    async def disconnect(self):
        self.is_connected = False


async def write(item):
    return await item._write_frame(
        seq=1, cmd_type=0x80, cmd_set=0x5A, cmd_id=0x62, payload=b"\x01"
    )


def test_queue_timeout_is_bounded_without_poisoning_live_transport(monkeypatch):
    monkeypatch.setattr(base.manager_transport_mod, "WRITE_LOCK_TIMEOUT", 0.01)
    async def scenario():
        item = base.make_manager()
        client = item._client = Client()
        await item._write_lock.acquire()
        with pytest.raises(base.manager_mod.DjiPowerConnectionError, match="queue timed out"):
            await write(item)
        assert item._write_lock.locked()  # The waiter must not release another writer's lock.
        assert item._transport_unhealthy_reason is None
        assert item._gatt_traffic.write_lock_timeout_count == 1
        assert item._gatt_traffic.backend_write_timeout_count == 0
        assert item._gatt_traffic.write_waiters == 0
        client.write_gatt_char.assert_not_awaited()
        item._write_lock.release()
        await write(item)
        assert item._gatt_traffic.write_completions_by_command == {"0x62": 1}
    asyncio.run(scenario())


def test_cancelled_and_old_generation_waiters_never_write(monkeypatch):
    async def scenario():
        item = base.make_manager()
        old = item._client = Client()
        await item._write_lock.acquire()
        pending = asyncio.create_task(write(item))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert item._gatt_traffic.write_waiters == 0
        assert item._write_lock.locked()
        pending = asyncio.create_task(write(item))
        await asyncio.sleep(0)
        new = item._client = Client()
        item._connection_generation += 1
        item._write_lock.release()
        with pytest.raises(base.manager_mod.DjiPowerConnectionError, match="connection changed"):
            await pending
        old.write_gatt_char.assert_not_awaited()
        new.write_gatt_char.assert_not_awaited()
        assert not item._write_lock.locked()
        assert item._gatt_traffic.stale_write_rejected_count == 1
    asyncio.run(scenario())


def test_subscription_isolation_and_setup_failure_phase(monkeypatch):
    async def scenario():
        item = base.make_manager()
        first, second = Client(), Client()
        device = base.BLEDevice(item.address, "Test")
        item._resolve_device_for_connection = AsyncMock(return_value=device)
        item._maybe_cleanup_stale_connections = AsyncMock()
        item._establish_client = AsyncMock(side_effect=[first, second])
        item._authenticate = AsyncMock()
        item._read_current_config = AsyncMock(return_value=config())
        await item._connect_auth_and_init()
        old_callback = first.callback
        await item.async_disconnect(reason="test")
        old_callback(None, bytearray(b"invalid"))
        assert item._last_notify_monotonic is None
        await item._connect_auth_and_init()
        generation = item._connection_generation
        future = asyncio.get_running_loop().create_future()
        item._pending[(generation, 77)] = (0x5A, 0x60, future)
        wire = response(0x60, bytes(20), 77).raw
        old_callback(None, bytearray(wire))
        assert not future.done()
        second.callback(None, bytearray(wire))
        assert future.done()
        assert item._gatt_traffic.stale_notification_count == 2
        await item.async_disconnect(reason="test")

        third = Client()
        item._establish_client = AsyncMock(return_value=third)
        async def failing_read():
            third.is_connected = False
            item._handle_disconnected_callback(third)
            raise base.manager_mod.DjiPowerConnectionError("test disconnect")
        item._read_current_config = failing_read
        with pytest.raises(base.manager_mod.DjiPowerConnectionError):
            await item._connect_auth_and_init()
        assert item.state.last_connection_failure_phase == "initial_config"
        failures = [
            event
            for event in item.connection_event_history
            if event["event"] == "connect_attempt_failed"
        ]
        assert failures[-1]["failure_phase"] == "initial_config"
    asyncio.run(scenario())


def test_find_device_uses_current_device_then_event_wait_and_retains_gate(monkeypatch):
    async def scenario():
        item = base.make_manager()
        device = base.BLEDevice(item.address, "Test")
        info = SimpleNamespace(address=item.address, device=device)

        def get_device(*_args, **_kwargs):
            return device

        process = AsyncMock(return_value=info)
        monkeypatch.setattr(
            base.ha_bluetooth, "async_ble_device_from_address", get_device
        )
        monkeypatch.setattr(
            base.ha_bluetooth,
            "async_process_advertisements",
            process,
            raising=False,
        )
        monkeypatch.setattr(
            base.ha_bluetooth,
            "BluetoothScanningMode",
            SimpleNamespace(PASSIVE="passive"),
            raising=False,
        )
        assert await item._find_device() is device
        process.assert_not_awaited()

        def no_device(*_args, **_kwargs):
            return None

        monkeypatch.setattr(
            base.ha_bluetooth, "async_ble_device_from_address", no_device
        )
        assert await item._find_device() is device
        matcher, match_dict, mode = process.call_args.args[1:4]
        assert matcher(info)
        assert not matcher(SimpleNamespace(address="02:00:00:00:00:02"))
        assert match_dict == {"address": item.address, "connectable": True}
        assert mode == "passive"
        process.side_effect = TimeoutError
        assert await item._find_device() is device  # Existing one-shot cache fallback.
        with pytest.raises(base.manager_mod.DjiPowerConnectionError):
            await item._find_device()
        item._last_ble_device = device
        item._cached_device_retry_used = False
        item._fresh_advertisement_required = True
        with pytest.raises(base.manager_mod.DjiPowerConnectionError):
            await item._find_device(allow_cached=False)
        assert item._fresh_advertisement_required
    asyncio.run(scenario())


def test_delayed_ack_and_old_backend_timeout_cannot_affect_new_link(monkeypatch):
    monkeypatch.setattr(base.manager_transport_mod, "GATT_WRITE_TIMEOUT", 0.01)

    async def scenario():
        item = base.make_manager()
        first = item._client = Client()
        frame = response(0x62, b"", 91)
        item._schedule_0x62_ack(frame)
        item._connection_generation += 1
        await asyncio.gather(*item._ack_tasks)
        first.write_gatt_char.assert_not_awaited()
        assert item._gatt_traffic.ack_scheduled_count == 1
        assert item._gatt_traffic.stale_write_rejected_count == 1

        started = asyncio.Event()

        async def blocked_write(*_a, **_kw):
            started.set()
            await asyncio.Event().wait()
        first.write_gatt_char.side_effect = blocked_write
        task = asyncio.create_task(write(item))
        await started.wait()
        item._client = Client()
        item._connection_generation += 1
        with pytest.raises(base.manager_mod.DjiPowerConnectionError, match="write timed out"):
            await task
        assert item._transport_unhealthy_reason is None
        assert item.state.last_error is None
        assert item._gatt_traffic.backend_write_timeout_count == 1
        assert not item._write_lock.locked()
        snapshot = base.load("manager_diagnostics").manager_runtime_snapshot(item)
        assert snapshot["gatt_traffic"]["write_attempts_by_command"] == {"0x62": 1}
        assert snapshot["gatt_traffic"]["scope"] == "manager_runtime_since_setup"
        snapshot["gatt_traffic"]["write_attempts_by_command"].clear()
        assert item._gatt_traffic.write_attempts_by_command == {"0x62": 1}
    asyncio.run(scenario())


def test_event_resolution_propagates_cancellation(monkeypatch):
    async def scenario():
        started, ended = asyncio.Event(), asyncio.Event()

        async def process(*_a):
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                ended.set()

        def no_device(*_args, **_kwargs):
            return None

        monkeypatch.setattr(
            base.ha_bluetooth, "async_ble_device_from_address", no_device
        )
        monkeypatch.setattr(
            base.ha_bluetooth,
            "async_process_advertisements",
            process,
            raising=False,
        )
        monkeypatch.setattr(
            base.ha_bluetooth,
            "BluetoothScanningMode",
            SimpleNamespace(PASSIVE="passive"),
            raising=False,
        )
        item = base.make_manager()
        task = asyncio.create_task(item._find_device())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert ended.is_set()
        assert item._last_ble_device is None
    asyncio.run(scenario())
