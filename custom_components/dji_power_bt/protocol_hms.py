"""DJI Power 0x66 HMS diagnostics parser."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from typing import Any

@dataclass(frozen=True, slots=True)
class HmsRecord:
    """Provisional DJI Power HMS record decoded from command 0x66."""

    alarm_id: int
    sensor_index: int
    report_level: int
    reserved: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "alarm_id": f"0x{self.alarm_id:08X}",
            "alarm_id_raw": self.alarm_id,
            "sensor_index": self.sensor_index,
            "report_level": self.report_level,
            "reserved": f"0x{self.reserved:04X}",
        }


@dataclass(frozen=True, slots=True)
class HmsReport:
    """Provisional parse result for one 0x66 notification."""

    parse_status: str
    timestamp_ms: int | None
    metadata_raw: int | None
    declared_record_count: int | None
    records: tuple[HmsRecord, ...]
    body_hex: str
    payload_length: int
    structure_provisional: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "parse_status": self.parse_status,
            "timestamp_ms": self.timestamp_ms,
            "metadata_raw": self.metadata_raw,
            "declared_record_count": self.declared_record_count,
            "record_count": len(self.records),
            "records": [record.as_dict() for record in self.records],
            "alarm_ids": [f"0x{record.alarm_id:08X}" for record in self.records],
            "body_hex": self.body_hex,
            "payload_length": self.payload_length,
            "structure_provisional": self.structure_provisional,
        }


def parse_0x66_hms(payload: bytes) -> HmsReport:
    """Parse the observed DJI Power 0x66 HMS shape conservatively.

    Observed payloads use the common 16-byte keyed header followed by a
    four-byte metadata/count prefix and zero or more eight-byte records. The
    layout is not published for DJI Power, so malformed or new variants are
    returned as ``unrecognized`` instead of being partially interpreted.
    """
    timestamp_ms: int | None = None
    if len(payload) >= 16 and payload[:4] == b"\x00\x00\x10\x00":
        timestamp_ms = int.from_bytes(payload[4:12], "little")
        body = payload[16:]
    else:
        body = payload

    body_hex = body.hex(" ")
    if len(body) < 4:
        return HmsReport(
            parse_status="unrecognized",
            timestamp_ms=timestamp_ms,
            metadata_raw=None,
            declared_record_count=None,
            records=(),
            body_hex=body_hex,
            payload_length=len(payload),
        )

    metadata_raw = int.from_bytes(body[0:2], "little")
    declared_count = int.from_bytes(body[2:4], "little")
    expected_length = 4 + declared_count * 8
    if len(body) != expected_length:
        return HmsReport(
            parse_status="unrecognized",
            timestamp_ms=timestamp_ms,
            metadata_raw=metadata_raw,
            declared_record_count=declared_count,
            records=(),
            body_hex=body_hex,
            payload_length=len(payload),
        )

    records: list[HmsRecord] = []
    for offset in range(4, len(body), 8):
        value = body[offset : offset + 8]
        records.append(
            HmsRecord(
                alarm_id=int.from_bytes(value[0:4], "little"),
                sensor_index=value[4],
                report_level=value[5],
                reserved=int.from_bytes(value[6:8], "little"),
            )
        )

    if not records:
        parse_status = "empty"
    elif any(record.report_level != 0 for record in records):
        parse_status = "records_nonzero_level"
    else:
        parse_status = "records_level_zero"
    return HmsReport(
        parse_status=parse_status,
        timestamp_ms=timestamp_ms,
        metadata_raw=metadata_raw,
        declared_record_count=declared_count,
        records=tuple(records),
        body_hex=body_hex,
        payload_length=len(payload),
    )


def update_hms_pattern_history(
    history: deque[dict[str, Any]],
    report: HmsReport,
    *,
    observed_at: str,
) -> None:
    """Record timestamp-independent 0x66 transitions in a bounded deque."""
    if history and history[-1].get("body_signature") == report.body_hex:
        history[-1]["last_seen_at"] = observed_at
        history[-1]["occurrence_count"] = int(
            history[-1].get("occurrence_count", 0)
        ) + 1
        return
    parse_without_timestamp = report.as_dict()
    parse_without_timestamp.pop("timestamp_ms", None)
    history.append(
        {
            "body_signature": report.body_hex,
            "first_seen_at": observed_at,
            "last_seen_at": observed_at,
            "occurrence_count": 1,
            "parse": parse_without_timestamp,
        }
    )



def split_0x66_hms_payload(payload: bytes) -> tuple[int | None, bytes]:
    """Return keyed-header timestamp and timestamp-independent HMS body."""
    if len(payload) >= 16 and payload[:4] == b"\x00\x00\x10\x00":
        return int.from_bytes(payload[4:12], "little"), payload[16:]
    return None, payload


def reuse_0x66_hms_report(
    previous: HmsReport | None,
    *,
    timestamp_ms: int | None,
    payload_length: int,
) -> HmsReport | None:
    """Refresh frame-specific fields of an already validated structural parse.

    The caller compares the timestamp-independent body as bytes before using this
    helper, so this path does not allocate another body hex string or walk records.
    """
    if previous is None:
        return None
    return replace(
        previous, timestamp_ms=timestamp_ms, payload_length=payload_length
    )
