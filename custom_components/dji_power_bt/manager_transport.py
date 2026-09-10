"""DJI application-protocol transport and write-verification mixin."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .const import CHAR_WRITE_C304, DOMAIN
from .manager_constants import GATT_WRITE_TIMEOUT
from .manager_types import DjiPowerAuthError, DjiPowerConnectionError, PendingVerification
from .manager_utils import utcnow_iso
from .protocol import (
    DEFAULT_STATUS_REQUEST_PAYLOAD, DumlFrame, PowerConfig, TariffSlot,
    build_duml_frame,
    parse_0x63_write_result, parse_power_config, parse_realtime_metrics,
    tariff_schedule_signature, write_result_ok,
)
from .write_policy import ACTIVE_WRITE_VERIFICATION, WriteVerificationPolicy, snapshot_is_fresh

_LOGGER = logging.getLogger(__name__)

class ManagerTransportMixin:
    def _alloc_seq(self) -> int:
        seq = self._next_seq
        self._next_seq = (self._next_seq + 1) & 0xFFFF
        return seq

    def _on_notify(self, _sender: str, data: bytearray) -> None:
        self._last_notify_monotonic = asyncio.get_running_loop().time()
        self.state.last_notify_at = utcnow_iso()
        for frame in self._reassembler.feed(bytes(data)):
            self._record_safe_payload(
                direction="rx",
                seq=frame.seq,
                cmd_type=frame.cmd_type,
                cmd_set=frame.cmd_set,
                cmd_id=frame.cmd_id,
                payload=frame.payload,
            )
            self._route_pending_response(frame)
            self._handle_unsolicited_frame(frame)

    def _route_pending_response(self, frame: DumlFrame) -> None:
        pending = self._pending.get((self._connection_generation, frame.seq))
        if pending is None:
            return
        cmd_set, cmd_id, future = pending
        if frame.cmd_set == cmd_set and frame.cmd_id == cmd_id and frame.cmd_type == 0x80 and not future.done():
            future.set_result(frame)

    def _fail_pending_requests(self, error: Exception) -> None:
        for _, _, future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    def _handle_unsolicited_frame(self, frame: DumlFrame) -> None:
        if frame.cmd_set != 0x5A:
            return
        now = utcnow_iso()
        self.state.last_notify_at = now
        if frame.cmd_id == 0x61:
            self.state.metrics = parse_realtime_metrics(frame.payload)
            self.state.last_0x61_at = now
            self._schedule_telemetry_publish()
            return
        if frame.cmd_id == 0x62:
            cfg = parse_power_config(frame.payload, source_cmd_id=frame.cmd_id)
            self.state.last_0x62_at = now
            self._apply_config(cfg, source="0x62")
            if frame.sender == 0xAB and frame.receiver == 0x02 and frame.cmd_type == 0x40:
                self._schedule_0x62_ack(frame)
            return
        if frame.cmd_id == 0x66:
            # 0x66 is a high-frequency liveness/auxiliary notification. Keep its
            # timestamp internally, but do not publish every packet to all HA
            # entities; the next throttled telemetry/config update will expose it.
            self.state.last_0x66_at = now

    def _schedule_telemetry_publish(self) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        interval = max(1.0, min(60.0, self.telemetry_update_interval))
        if self._last_telemetry_publish_monotonic is None or now - self._last_telemetry_publish_monotonic >= interval:
            self._publish_telemetry()
            return
        self._telemetry_publish_pending = True
        if self._telemetry_publish_timer is None:
            remaining = interval - (now - self._last_telemetry_publish_monotonic)
            self._telemetry_publish_timer = loop.call_later(max(0.0, remaining), self._publish_telemetry)

    def _publish_telemetry(self) -> None:
        self._telemetry_publish_timer = None
        self._telemetry_publish_pending = False
        self._last_telemetry_publish_monotonic = asyncio.get_running_loop().time()
        self._notify_listeners()

    def _cancel_telemetry_publish(self) -> None:
        if self._telemetry_publish_timer is not None:
            self._telemetry_publish_timer.cancel()
            self._telemetry_publish_timer = None
        self._telemetry_publish_pending = False
        self._last_telemetry_publish_monotonic = None

    def _apply_config(self, cfg: PowerConfig, *, source: str, notify: bool = True) -> None:
        self.state.config = cfg
        self._sync_device_registry_firmware()
        self._config_generation += 1
        # _apply_config is only called for a parsed device report/read response.
        # Optimistic ACK updates mutate the existing object without advancing this
        # timestamp, so cache freshness always means device-reported freshness.
        self._last_config_report_monotonic = asyncio.get_running_loop().time()
        if source.startswith("0x60"):
            self.state.last_0x60_refresh_at = utcnow_iso()
        self._resolve_verifications_from_config(source=source)
        if notify:
            self._notify_listeners()

    def _sync_device_registry_firmware(self) -> None:
        """Keep Home Assistant device firmware metadata aligned after 0x1000 arrives.

        Entity platforms are set up before the BLE manager starts, so the device
        registry may initially be created before the first 0x60/0x62 configuration
        report has supplied the firmware string. Update the registered device once
        the common 0x1000 value has been decoded, regardless of DJI Power model.
        """
        cfg = self.state.config
        firmware = cfg.firmware if cfg is not None else None
        if not firmware:
            return

        registry = dr.async_get(self.hass)
        device = registry.async_get_device(
            identifiers={(DOMAIN, self.address)}
        )
        if device is None or device.sw_version == firmware:
            return
        registry.async_update_device(device.id, sw_version=firmware)

    async def _write_frame(self, *, seq: int, cmd_type: int, cmd_set: int, cmd_id: int, payload: bytes, response: bool = True) -> bytes:
        client = self._client
        if client is None or not client.is_connected:
            raise DjiPowerConnectionError("BLE client is not connected")
        raw = build_duml_frame(seq=seq, cmd_type=cmd_type, cmd_set=cmd_set, cmd_id=cmd_id, payload=payload)
        self._record_safe_payload(
            direction="tx",
            seq=seq,
            cmd_type=cmd_type,
            cmd_set=cmd_set,
            cmd_id=cmd_id,
            payload=payload,
        )
        context = f"0x{cmd_set:02X}/0x{cmd_id:02X} seq=0x{seq:04X}"
        try:
            # Cover both waiting for a previous write and the backend GATT call.
            # This prevents a stuck ACK task from retaining the lock forever and
            # blocking authentication after reconnection.
            async with asyncio.timeout(GATT_WRITE_TIMEOUT):
                async with self._write_lock:
                    self._write_lock_acquired_monotonic = (
                        asyncio.get_running_loop().time()
                    )
                    self._write_lock_context = context
                    try:
                        await client.write_gatt_char(
                            CHAR_WRITE_C304,
                            raw,
                            response=response,
                        )
                    finally:
                        self._write_lock_acquired_monotonic = None
                        self._write_lock_context = None
        except TimeoutError as exc:
            now = utcnow_iso()
            self.state.gatt_write_timeout_count += 1
            self.state.last_gatt_write_timeout_at = now
            self.state.last_error = f"GATT write timeout: {context}"
            self.state.last_connection_error = self.state.last_error
            self.state.last_connection_error_at = now
            self._transport_unhealthy_reason = "gatt_write_timeout"
            self._notify_listeners()
            raise DjiPowerConnectionError(
                f"GATT write timed out after {GATT_WRITE_TIMEOUT:.0f}s: {context}"
            ) from exc
        return raw

    async def _request(self, *, cmd_id: int, payload: bytes, timeout: float = 10.0) -> DumlFrame:
        seq = self._alloc_seq()
        generation = self._connection_generation
        key = (generation, seq)
        future: asyncio.Future[DumlFrame] = asyncio.get_running_loop().create_future()
        self._pending[key] = (0x5A, cmd_id, future)
        try:
            await self._write_frame(seq=seq, cmd_type=0x20, cmd_set=0x5A, cmd_id=cmd_id, payload=payload)
            async with asyncio.timeout(timeout):
                return await future
        except TimeoutError as exc:
            raise TimeoutError(f"timeout waiting for 0x{cmd_id:02x} response") from exc
        finally:
            self._pending.pop(key, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                with contextlib.suppress(Exception):
                    future.exception()

    async def _authenticate(self) -> None:
        session_frame = await self._request(cmd_id=0x6A, payload=b"\x00")
        if len(session_frame.payload) < 5 or session_frame.payload[0] != 0:
            raise DjiPowerAuthError("invalid 0x6A session response")
        auth_payload = b"\x01" + session_frame.payload[1:5] + self.local_auth_key.encode("ascii") + b"\x00"
        auth_frame = await self._request(cmd_id=0x6A, payload=auth_payload)
        if not auth_frame.payload or auth_frame.payload[0] != 0:
            raise DjiPowerAuthError("0x6A authentication failed")
        self.state.authenticated = True
        _LOGGER.debug("DJI Power protocol authentication succeeded for %s", self.address)

    async def _read_current_config(self) -> PowerConfig:
        self.state.config_read_request_count += 1
        frame = await self._request(cmd_id=0x60, payload=DEFAULT_STATUS_REQUEST_PAYLOAD)
        return parse_power_config(frame.payload, source_cmd_id=frame.cmd_id)

    @staticmethod
    def _config_contains_tlv(cfg: PowerConfig, tlv_id: int) -> bool:
        return {
            0x1005: cfg.tlv_1005_value,
            0x100D: cfg.tlv_100d_value,
            0x1018: cfg.tlv_1018_value,
            0x101E: cfg.tlv_101e_value,
        }.get(tlv_id) is not None

    async def _config_for_write(
        self,
        *,
        required_tlv: int,
        max_age_s: float,
        refresh_source: str,
    ) -> PowerConfig:
        cfg = self.state.config
        now = asyncio.get_running_loop().time()
        if (
            cfg is not None
            and self._config_contains_tlv(cfg, required_tlv)
            and snapshot_is_fresh(
                last_report_monotonic=self._last_config_report_monotonic,
                now_monotonic=now,
                max_age_s=max_age_s,
            )
        ):
            self.state.config_cache_hit_count += 1
            return cfg

        cfg = await self._read_current_config()
        self._apply_config(cfg, source=refresh_source, notify=False)
        return cfg

    async def _send_0x63_and_apply(
        self,
        payload: bytes,
        *,
        expected_tlv: int | None = None,
        verification_key: str | None = None,
        expected_off_peak_power: int | None = None,
        expected_off_peak_enabled: bool | None = None,
        expected_peak_enabled: bool | None = None,
        expected_ac_output_enabled: bool | None = None,
        expected_output: tuple[int, int, bool] | None = None,
        expected_charge_limit: int | None = None,
        expected_discharge_limit: int | None = None,
        expected_energy_mode: str | None = None,
        expected_charging_mode: str | None = None,
        expected_tariff_slots: list[TariffSlot] | None = None,
        new_1018_value: bytes | None = None,
        new_1005_value: bytes | None = None,
        updated_output_states: list[OutputInterfaceState] | None = None,
        updated_charging_modes: list[ChargingModeOption] | None = None,
        updated_tariff_slots: list[TariffSlot] | None = None,
        verification_policy: WriteVerificationPolicy = ACTIVE_WRITE_VERIFICATION,
    ) -> None:
        """Complete a 0x63 transaction on its ACK, then verify state separately.

        The matching-sequence 0x63 response proves request completion. A later 0x62
        push or explicit 0x60 readback verifies device state. This separation avoids
        losing short OFF->ON transitions between periodic reports.
        """
        frame = await self._request(cmd_id=0x63, payload=payload)
        result = parse_0x63_write_result(frame.payload)
        # Verification must start from the state generation observed at ACK time.
        # A periodic 0x62 may arrive while the 0x63 request is in flight; using the
        # pre-request generation could falsely credit that older report as the
        # reflection of this write after the optimistic cache update below.
        baseline_generation = self._config_generation

        if expected_tlv is None:
            if expected_output is not None or expected_ac_output_enabled is not None:
                expected_tlv = 0x100D
            elif expected_charge_limit is not None or expected_discharge_limit is not None:
                expected_tlv = 0x1005
            elif expected_charging_mode is not None:
                expected_tlv = 0x101E
            elif expected_tariff_slots is not None:
                expected_tlv = 0x1016
            else:
                expected_tlv = 0x1018

        if verification_key is None:
            verification_key = f"property_0x{expected_tlv:04x}"

        if not write_result_ok(result, expected_tlv):
            self.state.last_write_result = f"0x{expected_tlv:04x} NG: {result}"
            self.state.reflection_confirmed = False
            self.state.reflection_source = "0x63_ack_error"
            self._notify_listeners()
            raise HomeAssistantError(
                f"DJI Power 0x{expected_tlv:04x} write failed: {result}"
            )

        acknowledged_at = utcnow_iso()
        self.state.last_write_result = "0x63_ack_ok"
        self.state.last_write_ack_at = acknowledged_at
        self.state.last_write_sequence = frame.seq
        self.state.last_write_property = verification_key
        self.state.reflection_confirmed = None
        self.state.reflection_source = "0x63_ack_pending_verification"

        cfg = self.state.config
        if cfg is not None:
            if new_1018_value is not None:
                cfg.tlv_1018_value = new_1018_value
            if new_1005_value is not None:
                cfg.tlv_1005_value = new_1005_value
            if expected_off_peak_power is not None:
                cfg.off_peak_charging_power_w = expected_off_peak_power
            if expected_off_peak_enabled is not None:
                cfg.off_peak_charge_raw = 1 if expected_off_peak_enabled else 2
            if expected_peak_enabled is not None:
                cfg.peak_discharge_raw = 1 if expected_peak_enabled else 2
            if expected_energy_mode is not None:
                cfg.energy_saver_raw = {"disabled": 1, "scheduled": 2}[
                    expected_energy_mode
                ]
            if updated_output_states is not None:
                cfg.output_interface_states = list(updated_output_states)
            elif expected_ac_output_enabled is not None:
                record = cfg.get_output_state(0x02, 1)
                if record is not None:
                    record.raw_state = 1 if expected_ac_output_enabled else 2
                    record.raw_value = record.value_with_state(expected_ac_output_enabled)
            if updated_charging_modes is not None:
                cfg.charging_modes = list(updated_charging_modes)
            if updated_tariff_slots is not None:
                cfg.tariff_slots = list(updated_tariff_slots)
            if expected_charge_limit is not None:
                cfg.charge_limit_percent = expected_charge_limit
            if expected_discharge_limit is not None:
                cfg.discharge_limit_percent = expected_discharge_limit
        expected_tariff_schedule = (
            tariff_schedule_signature(expected_tariff_slots)
            if expected_tariff_slots is not None
            else None
        )
        expected: dict[str, Any] = {
            "expected_off_peak_power": expected_off_peak_power,
            "expected_off_peak_enabled": expected_off_peak_enabled,
            "expected_peak_enabled": expected_peak_enabled,
            "expected_ac_output_enabled": expected_ac_output_enabled,
            "expected_output": expected_output,
            "expected_charge_limit": expected_charge_limit,
            "expected_discharge_limit": expected_discharge_limit,
            "expected_energy_mode": expected_energy_mode,
            "expected_charging_mode": expected_charging_mode,
            "expected_tariff_schedule": expected_tariff_schedule,
        }
        history_record: dict[str, Any] = {
            "property": verification_key,
            "sequence": frame.seq,
            "expected_tlv": f"0x{expected_tlv:04x}",
            "acknowledged": True,
            "acknowledged_at": acknowledged_at,
            "result": result,
            "expected": expected,
            "verified": None,
            "verification_source": None,
            "verified_at": None,
        }
        self._write_history.append(history_record)
        self._schedule_write_verification(
            key=verification_key,
            expected=expected,
            baseline_generation=baseline_generation,
            ack_sequence=frame.seq,
            acknowledged_at=acknowledged_at,
            history_record=history_record,
            policy=verification_policy,
        )
        self._notify_listeners()

    def _config_matches_expected(self, expected: dict[str, Any]) -> bool:
        cfg = self.state.config
        if cfg is None:
            return False
        checks = [
            expected.get("expected_off_peak_power") is None
            or cfg.off_peak_charging_power_w == expected["expected_off_peak_power"],
            expected.get("expected_off_peak_enabled") is None
            or cfg.off_peak_charge_enabled == expected["expected_off_peak_enabled"],
            expected.get("expected_peak_enabled") is None
            or cfg.peak_discharge_enabled == expected["expected_peak_enabled"],
            expected.get("expected_ac_output_enabled") is None
            or cfg.ac_output_enabled == expected["expected_ac_output_enabled"],
            expected.get("expected_charge_limit") is None
            or cfg.charge_limit_percent == expected["expected_charge_limit"],
            expected.get("expected_discharge_limit") is None
            or cfg.discharge_limit_percent == expected["expected_discharge_limit"],
            expected.get("expected_energy_mode") is None
            or cfg.energy_optimization_mode == expected["expected_energy_mode"],
            expected.get("expected_charging_mode") is None
            or cfg.charging_mode == expected["expected_charging_mode"],
            expected.get("expected_tariff_schedule") is None
            or tariff_schedule_signature(cfg.tariff_slots)
            == expected["expected_tariff_schedule"],
        ]

        expected_output = expected.get("expected_output")
        if expected_output is not None:
            interface_type, port_index, enabled = expected_output
            record = cfg.get_output_state(interface_type, port_index)
            checks.append(record is not None and record.enabled == enabled)

        return all(checks)

    def _schedule_write_verification(
        self,
        *,
        key: str,
        expected: dict[str, Any],
        baseline_generation: int,
        ack_sequence: int,
        acknowledged_at: str,
        history_record: dict[str, Any],
        policy: WriteVerificationPolicy,
    ) -> None:
        revision = self._verification_revisions.get(key, 0) + 1
        self._verification_revisions[key] = revision
        old_pending = self._pending_verifications.pop(key, None)
        old_task = self._verification_tasks.pop(key, None)
        if old_task is not None and not old_task.done():
            old_task.cancel()
        if old_pending is not None:
            old_pending.history_record["verified"] = None
            old_pending.history_record["verification_source"] = (
                "superseded_by_new_write"
            )
            old_pending.history_record["verified_at"] = utcnow_iso()
        pending = PendingVerification(
            key=key,
            revision=revision,
            expected=expected,
            baseline_generation=baseline_generation,
            ack_sequence=ack_sequence,
            acknowledged_at=acknowledged_at,
            history_record=history_record,
            policy=policy,
        )
        self._pending_verifications[key] = pending
        self.state.write_verification_pending = True
        task = self.hass.loop.create_task(self._verify_write_after_delay(pending))
        self._verification_tasks[key] = task

    def _resolve_verifications_from_config(self, *, source: str) -> None:
        for key, pending in list(self._pending_verifications.items()):
            if self._verification_revisions.get(key) != pending.revision:
                continue
            if self._config_matches_expected(pending.expected):
                self._finish_write_verification(
                    pending, confirmed=True, source=source
                )

    def _finish_write_verification(
        self, pending: PendingVerification, *, confirmed: bool | None, source: str
    ) -> None:
        current = self._pending_verifications.get(pending.key)
        if current is not pending:
            return
        self._pending_verifications.pop(pending.key, None)
        task = self._verification_tasks.pop(pending.key, None)
        if (
            task is not None
            and task is not asyncio.current_task()
            and not task.done()
        ):
            task.cancel()
        pending.history_record["verified"] = confirmed
        pending.history_record["verification_source"] = source
        pending.history_record["verified_at"] = utcnow_iso()
        if self.state.last_write_sequence == pending.ack_sequence:
            self.state.reflection_confirmed = confirmed
            self.state.reflection_source = source
            if confirmed is False:
                self.state.last_write_result = "0x63_ack_ok_readback_mismatch"
        self.state.write_verification_pending = bool(self._pending_verifications)

    async def _verify_write_after_delay(
        self, pending: PendingVerification
    ) -> None:
        try:
            # Prefer the periodic 0x62 report. Power 2000 reports roughly every
            # 10 seconds, so an immediate 0.6-second readback creates needless
            # large GATT transfers and can overload a shared Bluetooth proxy.
            await asyncio.sleep(pending.policy.wait_for_report_s)
            current = self._pending_verifications.get(pending.key)
            if current is not pending:
                return
            if (
                self._config_generation > pending.baseline_generation
                and self._config_matches_expected(pending.expected)
            ):
                self._finish_write_verification(
                    pending, confirmed=True, source="device_report"
                )
                self._notify_listeners()
                return

            if not pending.policy.allow_readback:
                # High-frequency off-peak power writes are completed by the 0x63
                # ACK. Missing the intermediate value in the 10-second 0x62 cycle
                # is not a write failure, so expire verification without forcing
                # another full 0x60 read.
                self.state.passive_verification_timeout_count += 1
                self._finish_write_verification(
                    pending,
                    confirmed=None,
                    source=pending.policy.timeout_source,
                )
                self._notify_listeners()
                return

            async with self._operation_lock:
                current = self._pending_verifications.get(pending.key)
                if current is not pending:
                    return
                await self._ensure_ready()
                self.state.verification_readback_count += 1
                cfg = await self._read_current_config()
                self._apply_config(cfg, source="0x60_write_verify", notify=False)
                if self._pending_verifications.get(pending.key) is pending:
                    self._finish_write_verification(
                        pending,
                        confirmed=self._config_matches_expected(pending.expected),
                        source="0x60_readback",
                    )
                self._notify_listeners()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.debug(
                "Delayed verification after 0x63 failed for %s/%s: %s",
                self.address,
                pending.key,
                exc,
            )
            if self._pending_verifications.get(pending.key) is pending:
                pending.history_record["verification_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                self.state.write_verification_pending = bool(
                    self._pending_verifications
                )
                self._notify_listeners()

    def _cancel_write_verifications(self) -> None:
        for task in self._verification_tasks.values():
            if not task.done():
                task.cancel()
        self._verification_tasks.clear()
        self._pending_verifications.clear()
        self.state.write_verification_pending = False

    def _schedule_0x62_ack(self, frame: DumlFrame) -> None:
        task = self.hass.loop.create_task(self._ack_0x62(frame))
        self._ack_tasks.add(task)
        task.add_done_callback(self._ack_tasks.discard)

    def _cancel_ack_tasks(self) -> None:
        for task in tuple(self._ack_tasks):
            if not task.done():
                task.cancel()
        self._ack_tasks.clear()

    async def _ack_0x62(self, frame: DumlFrame) -> None:
        try:
            await self._write_frame(
                seq=frame.seq,
                cmd_type=0x80,
                cmd_set=frame.cmd_set,
                cmd_id=frame.cmd_id,
                payload=b"\x01",
            )
        except Exception as exc:  # noqa: best-effort ACK
            _LOGGER.debug("Failed to ACK 0x62: %s", exc)

    async def _ensure_ready(self) -> None:
        if not self.state.ble_enabled:
            raise HomeAssistantError("DJI Power BLE is disabled")
        if not self.state.connected or not self.state.authenticated:
            raise HomeAssistantError("DJI Power is not connected/authenticated")
