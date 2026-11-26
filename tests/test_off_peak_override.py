"""Exercise the public setters against station reports with a below-minimum target."""
import asyncio
from unittest.mock import AsyncMock

import pytest

import test_ble_reliability as ble
import test_manager_v070 as base


def station_report(power, model=0x94, *, charging=True, mode=2, minimum=600, maximum=1500):
    raw = bytearray(base._scheduled_1018_value(
        mode_raw=mode, off_peak_raw=1 if charging else 2, power_w=power
    ))
    raw[4:8] = maximum.to_bytes(4, "little")
    raw[8:12] = minimum.to_bytes(4, "little")
    if model == 0x9E:
        raw.extend(bytes(range(17)))
    raw[16:] = bytes(range(len(raw) - 16))
    return ble.protocol.parse_power_config(ble.tlv(0x1018, raw), source_cmd_id=0x62)


def manager(model=0x94, override=200):
    entry = base.FakeEntry()
    entry.data = {**entry.data, "model_code": model}
    entry.options = {"off_peak_min_override_w": override}
    item = base.manager_mod.DjiPowerManager(
        base.FakeHass(asyncio.get_running_loop()), entry, connection_operation_lock=asyncio.Lock()
    )
    item.state.connected = item.state.authenticated = True
    item.state.connection_phase = "ready"
    item._apply_config(station_report(600, model), source="0x62", notify=False)
    item._request = AsyncMock(return_value=ble.response(
        0x63, ble.protocol.build_keyed_header(timestamp_ms=1) + ble.tlv(0x1018, bytes(4))
    ))
    return item


@pytest.mark.parametrize("model", [0x94, 0x9E])
def test_midpoint_display_and_shared_writer(model):
    async def run():
        item = manager(model)
        assert item.effective_off_peak_min_w == 200
        await item.async_set_scheduled_energy_settings(off_peak_charging_power=300, off_peak_charging=True)
        assert item.reported_off_peak_w == 600
        report = station_report(1050, model)
        raw = report.tlv_1018_value
        item._apply_config(report, source="0x62")
        assert item.reported_off_peak_w == 1050
        assert item.displayed_off_peak_power_w == 300
        assert item.state.reflection_confirmed is None
        assert item.state.reflection_source == "0x62_reported_midpoint"
        await item.async_set_off_peak_power(300)
        assert item._request.await_count == 1
        await item.async_set_peak_discharge_enabled(True)
        expected = bytearray(raw)
        expected[2] = 1
        expected[12:16] = (300).to_bytes(4, "little")
        assert ble.tlv(0x1018, expected) in item._request.await_args.kwargs["payload"]
        item._apply_config(station_report(1050, model), source="0x62")
        item._off_peak_sent_at -= 301
        await item.async_set_off_peak_power(300)
        assert item._request.await_count == 3
        item._apply_config(station_report(1050, model), source="0x62")
        await item.async_set_off_peak_power(1050)
        assert item._request.await_count == 4
        assert item.displayed_off_peak_power_w == 1050
        item._cancel_write_verifications()
    asyncio.run(run())


@pytest.mark.parametrize("model,maximum,midpoint", [(0x94, 1500, 1050), (0x9E, 1440, 1020)])
@pytest.mark.parametrize("initially_enabled", [False, True])
def test_off_requests_preserve_target_and_skip_timed_resend(model, maximum, midpoint, initially_enabled):
    async def run():
        item = manager(model)
        def report(power, charging):
            item._apply_config(station_report(power, model, maximum=maximum, charging=charging), source="0x62")

        report(600, initially_enabled)
        await item.async_set_scheduled_energy_settings(off_peak_charging=False, off_peak_charging_power=200)
        assert item.displayed_off_peak_power_w == 200
        report(midpoint, False)
        assert item.displayed_off_peak_power_w == 200
        assert item.reported_off_peak_w == midpoint
        item._off_peak_sent_at -= 301
        await item.async_set_scheduled_energy_settings(off_peak_charging=False, off_peak_charging_power=200)
        await item.async_set_off_peak_power(200)
        assert item._request.await_count == 1

        # A changed target still takes effect immediately while charging is off.
        await item.async_set_off_peak_power(250)
        report(midpoint, False)
        assert item.displayed_off_peak_power_w == 250
        expected = bytearray(item.state.config.tlv_1018_value)
        expected[12:16] = (250).to_bytes(4, "little")
        assert ble.tlv(0x1018, expected) in item._request.await_args.kwargs["payload"]
        await item.async_set_scheduled_energy_settings(off_peak_charging=True)
        expected[3] = 1
        assert ble.tlv(0x1018, expected) in item._request.await_args.kwargs["payload"]
        assert item._request.await_count == 3
        report(midpoint, True)
        report(midpoint, False)
        assert item.displayed_off_peak_power_w == 250
        item._cancel_write_verifications()
    asyncio.run(run())


@pytest.mark.parametrize("change", ["other", "bounds", "mode", "disconnect"])
def test_hold_invalidation(change):
    async def run():
        item = manager()
        await item.async_set_off_peak_power(200)
        item._apply_config(station_report(200), source="0x62")
        assert item.state.reflection_confirmed is True
        if change == "disconnect":
            item._cancel_write_verifications()
            cfg = station_report(1050)
        else:
            cfg = station_report(
                600 if change == "other" else 1050,
                minimum=500 if change == "bounds" else 600, mode=1 if change == "mode" else 2,
            )
        item._apply_config(cfg, source="0x62")
        assert item.displayed_off_peak_power_w == cfg.off_peak_charging_power_w
        if change == "other":
            await item.async_set_off_peak_power(200)
            assert item._request.await_count == 2
        item._cancel_write_verifications()
    asyncio.run(run())


def test_low_write_failure_and_freshness():
    async def run():
        item = manager()
        for invalid in (190, 205, 1510):
            with pytest.raises(ValueError):
                await item.async_set_off_peak_power(invalid)
        item._request.assert_not_awaited()
        item._request.side_effect = base.HomeAssistantError("No ACK")
        with pytest.raises(base.HomeAssistantError):
            await item.async_set_off_peak_power(300)
        assert item.displayed_off_peak_power_w == 600
        item._request.side_effect = None
        await item.async_set_off_peak_power(300)
        item._last_config_report_monotonic = None
        item._read_current_config = AsyncMock(return_value=station_report(800))
        await item.async_set_off_peak_power(300)
        item._read_current_config.assert_awaited_once()
        assert item._request.await_count == 3
        item._cancel_write_verifications()
    asyncio.run(run())


@pytest.mark.parametrize("model,override", [(0x94, None), (0x9E, 190), (0x98, 200)])
def test_override_is_optional_and_model_scoped(model, override):
    async def run():
        item = manager(model, override)
        assert item.effective_off_peak_min_w == 600
        with pytest.raises((ValueError, base.HomeAssistantError)):
            await item.async_set_off_peak_power(300)
        item._request.assert_not_awaited()
    asyncio.run(run())


def test_combined_write_midpoint_with_wrong_flag_uses_readback():
    async def run():
        item = manager()
        await item.async_set_scheduled_energy_settings(
            off_peak_charging_power=300, peak_discharging=True
        )
        # This station reports peak discharging OFF although the request enabled it.
        item._apply_config(station_report(1050), source="0x62")
        pending = item._pending_verifications["scheduled_energy_settings"]
        assert item.state.write_verification_pending
        assert item.state.reflection_confirmed is None
        item._read_current_config = AsyncMock(return_value=station_report(1050))
        pending.policy = base.load("write_policy").WriteVerificationPolicy(True, 0, "timeout")
        await item._verification_tasks[pending.key]
        item._read_current_config.assert_awaited_once()
        assert item.state.reflection_confirmed is False
        assert item.state.reflection_source == "0x60_readback"
        item._cancel_write_verifications()
    asyncio.run(run())


def test_rejected_replacement_preserves_prior_acknowledged_request():
    async def run():
        item = manager()
        await item.async_set_off_peak_power(300)
        item._apply_config(station_report(1050), source="0x62")
        item._request.return_value = ble.response(
            0x63, ble.protocol.build_keyed_header(timestamp_ms=1)
            + ble.tlv(0x1018, (1).to_bytes(4, "little"))
        )
        with pytest.raises(base.HomeAssistantError):
            await item.async_set_off_peak_power(310)
        assert item.displayed_off_peak_power_w == 300
        assert item.reported_off_peak_w == 1050
        item._cancel_write_verifications()
    asyncio.run(run())
