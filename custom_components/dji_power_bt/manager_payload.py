"""Payload capture and high-rate HMS diagnostics mixin."""
from __future__ import annotations

import asyncio
from typing import Any

from .const import SAFE_PAYLOAD_COMMANDS
from .manager_constants import HMS_PATTERN_HISTORY_LIMIT
from .manager_utils import utcnow_iso
from .protocol import (
    parse_0x66_hms, reuse_0x66_hms_report, split_0x66_hms_payload,
    update_hms_pattern_history,
)

class ManagerPayloadMixin:
    @property
    def payload_capture_active(self) -> bool:
        deadline = self._capture_active_until_monotonic
        if deadline is None:
            return False
        if asyncio.get_running_loop().time() <= deadline:
            return True
        self._capture_active_until_monotonic = None
        if self._capture_finished_at is None:
            self._capture_finished_at = utcnow_iso()
        return False

    @property
    def latest_payloads(self) -> dict[str, dict[str, Any]]:
        return dict(self._latest_payloads)

    @property
    def captured_payloads(self) -> list[dict[str, Any]]:
        # Refresh expiry metadata before returning diagnostics.
        _ = self.payload_capture_active
        return list(self._capture_frames)

    @property
    def write_history(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._write_history]

    @property
    def reassembly_diagnostics(self) -> dict[str, int]:
        return self._reassembler.diagnostics()

    @property
    def payload_capture_info(self) -> dict[str, Any]:
        return {
            "active": self.payload_capture_active,
            "started_at": self._capture_started_at,
            "finished_at": self._capture_finished_at,
            "frame_count": len(self._capture_frames),
            "max_frames": self._capture_max_frames,
            "authentication_payloads_excluded": True,
        }

    @property
    def hms_diagnostics(self) -> dict[str, Any]:
        return {
            "parser_structure_provisional": True,
            "latest_report": (
                self.state.latest_hms_report.as_dict()
                if self.state.latest_hms_report is not None
                else None
            ),
            "timestamp_excluded_pattern_history": [
                dict(item) for item in self._hms_pattern_history
            ],
            "pattern_history_limit": HMS_PATTERN_HISTORY_LIMIT,
            "full_parse_count": self._hms_full_parse_count,
            "fast_path_hit_count": self._hms_fast_path_hit_count,
        }

    @property
    def write_lock_age_s(self) -> float | None:
        acquired = self._write_lock_acquired_monotonic
        if acquired is None:
            return None
        return max(0.0, asyncio.get_running_loop().time() - acquired)

    @property
    def ack_task_count(self) -> int:
        return sum(not task.done() for task in self._ack_tasks)

    def _record_safe_payload(
        self,
        *,
        direction: str,
        seq: int,
        cmd_type: int,
        cmd_set: int,
        cmd_id: int,
        payload: bytes,
    ) -> None:
        if cmd_set != 0x5A or cmd_id not in SAFE_PAYLOAD_COMMANDS:
            return
        record = {
            "received_at": utcnow_iso(),
            "direction": direction,
            "sequence": seq,
            "command_type": f"0x{cmd_type:02X}",
            "command_set": f"0x{cmd_set:02X}",
            "command_id": f"0x{cmd_id:02X}",
            "payload_length": len(payload),
            "payload_hex": payload.hex(" "),
        }
        if direction == "rx" and cmd_id == 0x66:
            timestamp_ms, body = split_0x66_hms_payload(payload)
            if (
                self.state.latest_hms_report is not None
                and self._last_hms_body == body
            ):
                report = reuse_0x66_hms_report(
                    self.state.latest_hms_report,
                    timestamp_ms=timestamp_ms,
                    payload_length=len(payload),
                )
                self._hms_fast_path_hit_count += 1
            else:
                report = parse_0x66_hms(payload)
                self._last_hms_body = body
                self._hms_full_parse_count += 1
            self.state.latest_hms_report = report
            observed_at = record["received_at"]
            update_hms_pattern_history(
                self._hms_pattern_history,
                report,
                observed_at=observed_at,
            )
            record["timestamp_excluded_body_hex"] = report.body_hex
            record["hms_parse"] = report.as_dict()
        self._latest_payloads[f"{direction}_0x{cmd_id:02X}"] = record
        if self.payload_capture_active:
            self._capture_frames.append(record)
            if len(self._capture_frames) >= self._capture_max_frames:
                self._capture_active_until_monotonic = None
                self._capture_finished_at = utcnow_iso()
