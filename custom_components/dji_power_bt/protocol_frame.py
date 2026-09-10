"""DJI DUM-like framing, CRC, TLV scanning and stream reassembly."""
from __future__ import annotations

from dataclasses import dataclass
import time

from .protocol_common import u16le

@dataclass(slots=True)
class DumlFrame:
    raw: bytes
    length: int
    version: int
    header_crc_ok: bool
    crc16_ok: bool
    sender: int
    receiver: int
    seq: int
    cmd_type: int
    cmd_set: int
    cmd_id: int
    payload: bytes

    @property
    def raw_hex(self) -> str:
        return self.raw.hex(" ")

    @property
    def payload_hex(self) -> str:
        return self.payload.hex(" ")

    def summary(self) -> str:
        return (
            f"seq=0x{self.seq:04x} "
            f"sender=0x{self.sender:02x}->0x{self.receiver:02x} "
            f"type=0x{self.cmd_type:02x} "
            f"cmd=0x{self.cmd_set:02x}/0x{self.cmd_id:02x} "
            f"payload_len={len(self.payload)} "
            f"crc={'OK' if self.crc16_ok else 'NG'}"
        )


def crc8_dji(data: bytes) -> int:
    crc = 0x77
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8C
            else:
                crc >>= 1
            crc &= 0xFF
    return crc


def crc16_dji(data: bytes) -> int:
    crc = 0x3692
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
            crc &= 0xFFFF
    return crc


def duml_length_from_header(data: bytes | bytearray) -> int:
    if len(data) < 3 or data[0] != 0x55:
        raise ValueError("not a DUM-like frame header")
    return data[1] | ((data[2] & 0x03) << 8)


def build_duml_frame(
    *,
    sender: int = 0x02,
    receiver: int = 0xAB,
    seq: int,
    cmd_type: int = 0x20,
    cmd_set: int,
    cmd_id: int,
    payload: bytes,
) -> bytes:
    length = 13 + len(payload)
    if length > 0x03FF:
        raise ValueError(f"frame too long: {length}")
    length_version = length | 0x0400
    head3 = bytes([0x55]) + length_version.to_bytes(2, "little")
    head_crc = crc8_dji(head3)
    frame_without_crc = (
        head3
        + bytes([head_crc, sender, receiver])
        + seq.to_bytes(2, "little")
        + bytes([cmd_type, cmd_set, cmd_id])
        + payload
    )
    crc = crc16_dji(frame_without_crc)
    return frame_without_crc + crc.to_bytes(2, "little")


def parse_duml_frame(raw: bytes) -> DumlFrame:
    if len(raw) < 13:
        raise ValueError(f"frame too short: {len(raw)}")
    if raw[0] != 0x55:
        raise ValueError("not a DUM-like frame")
    length = duml_length_from_header(raw)
    if len(raw) != length:
        raise ValueError(f"length mismatch: header={length}, actual={len(raw)}")
    version = raw[2] >> 2
    header_crc_ok = crc8_dji(raw[:3]) == raw[3]
    expected_crc = int.from_bytes(raw[-2:], "little")
    actual_crc = crc16_dji(raw[:-2])
    return DumlFrame(
        raw=raw,
        length=length,
        version=version,
        header_crc_ok=header_crc_ok,
        crc16_ok=expected_crc == actual_crc,
        sender=raw[4],
        receiver=raw[5],
        seq=int.from_bytes(raw[6:8], "little"),
        cmd_type=raw[8],
        cmd_set=raw[9],
        cmd_id=raw[10],
        payload=raw[11:-2],
    )


class DumlReassembler:
    """Reassemble DJI frames from an arbitrary ATT notification byte stream.

    A GATT notification is not a DJI frame boundary. One frame may be split over
    notifications, and one notification may contain multiple frames. Frame length
    and both DJI CRCs are used for extraction; a later 0x55 byte is only a
    resynchronisation candidate after a malformed header/frame.
    """

    MIN_FRAME_LENGTH = 13
    MAX_FRAME_LENGTH = 0x03FF
    MAX_BUFFER_LENGTH = 8192

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.frames_ok = 0
        self.invalid_length_count = 0
        self.header_crc_error_count = 0
        self.frame_crc_error_count = 0
        self.discarded_byte_count = 0
        self._partial_started_monotonic: float | None = None
        self.partial_timeout_count = 0

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()
        self._partial_started_monotonic = None

    def diagnostics(self) -> dict[str, int]:
        return {
            "buffered_bytes": len(self._buffer),
            "frames_ok": self.frames_ok,
            "invalid_length_count": self.invalid_length_count,
            "header_crc_error_count": self.header_crc_error_count,
            "frame_crc_error_count": self.frame_crc_error_count,
            "discarded_byte_count": self.discarded_byte_count,
            "partial_timeout_count": self.partial_timeout_count,
        }

    def _discard(self, count: int) -> None:
        """Discard invalid/noise bytes and count them for diagnostics."""
        if count <= 0:
            return
        del self._buffer[:count]
        self.discarded_byte_count += count

    def _consume(self, count: int) -> None:
        """Consume a successfully parsed frame without counting it as discarded."""
        if count <= 0:
            return
        del self._buffer[:count]

    def feed(self, chunk: bytes) -> list[DumlFrame]:
        frames: list[DumlFrame] = []
        now = time.monotonic()
        if self._buffer and self._partial_started_monotonic is not None:
            if now - self._partial_started_monotonic > 10.0:
                self.partial_timeout_count += 1
                self._discard(len(self._buffer))
                self._partial_started_monotonic = None
        if chunk:
            if not self._buffer:
                self._partial_started_monotonic = now
            self._buffer.extend(chunk)

        if len(self._buffer) > self.MAX_BUFFER_LENGTH:
            # Retain only the tail beginning at the last possible sync byte.
            last_sync = self._buffer.rfind(b"\x55")
            if last_sync < 0:
                self._discard(len(self._buffer))
            else:
                self._discard(last_sync)

        while True:
            if not self._buffer:
                break

            if self._buffer[0] != 0x55:
                sync = self._buffer.find(b"\x55")
                if sync < 0:
                    self._discard(len(self._buffer))
                    break
                self._discard(sync)

            if len(self._buffer) < 4:
                break

            try:
                expected_len = duml_length_from_header(self._buffer)
            except ValueError:
                self._discard(1)
                continue

            if not (self.MIN_FRAME_LENGTH <= expected_len <= self.MAX_FRAME_LENGTH):
                self.invalid_length_count += 1
                self._discard(1)
                continue

            if crc8_dji(bytes(self._buffer[:3])) != self._buffer[3]:
                self.header_crc_error_count += 1
                self._discard(1)
                continue

            if len(self._buffer) < expected_len:
                break

            raw = bytes(self._buffer[:expected_len])
            try:
                frame = parse_duml_frame(raw)
            except ValueError:
                self.invalid_length_count += 1
                self._discard(1)
                continue

            if not frame.header_crc_ok:
                self.header_crc_error_count += 1
                self._discard(1)
                continue
            if not frame.crc16_ok:
                self.frame_crc_error_count += 1
                self._discard(1)
                continue

            self._consume(expected_len)
            if not self._buffer:
                self._partial_started_monotonic = None
            else:
                self._partial_started_monotonic = now
            self.frames_ok += 1
            frames.append(frame)

        if not self._buffer:
            self._partial_started_monotonic = None
        return frames


# -----------------------------------------------------------------------------
# TLV parsing
# -----------------------------------------------------------------------------

def iter_tlvs(payload: bytes) -> list[tuple[int, int, bytes]]:
    result: list[tuple[int, int, bytes]] = []
    pos = 0
    while pos + 4 <= len(payload):
        tlv_id = u16le(payload, pos)
        length = u16le(payload, pos + 2)
        value_start = pos + 4
        value_end = value_start + length
        if value_end > len(payload):
            break
        result.append((tlv_id, value_start, payload[value_start:value_end]))
        pos = value_end
    return result


def find_tlvs(
    payload: bytes,
    tlv_id: int,
    *,
    expected_lengths: set[int] | None = None,
) -> list[tuple[int, bytes]]:
    found: list[tuple[int, bytes]] = []
    needle = tlv_id.to_bytes(2, "little")
    for offset in range(0, max(0, len(payload) - 4 + 1)):
        if payload[offset : offset + 2] != needle:
            continue
        length = u16le(payload, offset + 2)
        value_start = offset + 4
        value_end = value_start + length
        if value_end > len(payload):
            continue
        if expected_lengths is not None and length not in expected_lengths:
            continue
        found.append((offset, payload[value_start:value_end]))
    return found


def find_first_tlv(
    payload: bytes,
    tlv_id: int,
    *,
    expected_lengths: set[int] | None = None,
    min_length: int = 0,
) -> tuple[int, bytes] | None:
    for offset, value in find_tlvs(payload, tlv_id, expected_lengths=expected_lengths):
        if len(value) >= min_length:
            return offset, value
    return None
