"""Tariff-period calculation helpers for DJI Power."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .protocol import TariffSlot

MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY
VALID_PERIODS = {"peak", "off_peak"}


@dataclass(frozen=True, slots=True)
class TariffPeriodStatus:
    """Calculated tariff-period state for one point in local time."""

    state: str
    active_slot: dict[str, Any] | None
    next_change: datetime | None
    next_period: str | None
    conflict: bool
    valid: bool


def _parse_hhmm(value: str) -> int | None:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _slot_weekdays(slot: TariffSlot) -> list[int] | None:
    """Return Python weekday numbers (Mon=0 ... Sun=6) for the slot start day."""
    if slot.day_mode_raw == 0x01:
        return list(range(7))
    if slot.day_mode_raw != 0x02:
        return None

    weekdays: list[int] = []
    for weekday in range(7):
        if slot.day_mask & (1 << weekday):
            weekdays.append(weekday)
    return weekdays or None


def _state_for_indexes(slots: list[TariffSlot], indexes: list[int]) -> str:
    if not indexes:
        return "none"
    kinds = {slots[index].kind for index in indexes}
    if not kinds.issubset(VALID_PERIODS):
        return "unknown"
    if len(kinds) == 1:
        return next(iter(kinds))
    return "unknown"


def evaluate_tariff_period(
    slots: list[TariffSlot] | None,
    now: datetime,
) -> TariffPeriodStatus:
    """Evaluate current and next tariff period from 0x1017 slots.

    The weekday mask applies to the slot's start day. If end time is equal to
    or earlier than start time, the slot ends on the following day.
    """
    if slots is None:
        return TariffPeriodStatus(
            state="unknown",
            active_slot=None,
            next_change=None,
            next_period=None,
            conflict=False,
            valid=False,
        )

    if not slots:
        return TariffPeriodStatus(
            state="none",
            active_slot=None,
            next_change=None,
            next_period=None,
            conflict=False,
            valid=True,
        )

    coverage: list[list[int]] = [[] for _ in range(MINUTES_PER_WEEK)]
    invalid = False

    for index, slot in enumerate(slots):
        if slot.kind not in VALID_PERIODS:
            invalid = True
            continue

        start_minute = _parse_hhmm(slot.start_time)
        end_minute = _parse_hhmm(slot.end_time)
        weekdays = _slot_weekdays(slot)
        if start_minute is None or end_minute is None or weekdays is None:
            invalid = True
            continue

        for weekday in weekdays:
            start = weekday * MINUTES_PER_DAY + start_minute
            end = weekday * MINUTES_PER_DAY + end_minute
            if end <= start:
                end += MINUTES_PER_DAY

            for absolute_minute in range(start, end):
                coverage[absolute_minute % MINUTES_PER_WEEK].append(index)

    conflict = any(len(indexes) > 1 for indexes in coverage)

    if invalid:
        return TariffPeriodStatus(
            state="unknown",
            active_slot=None,
            next_change=None,
            next_period=None,
            conflict=conflict,
            valid=False,
        )

    current_minute = (
        now.weekday() * MINUTES_PER_DAY
        + now.hour * 60
        + now.minute
    ) % MINUTES_PER_WEEK
    active_indexes = coverage[current_minute]
    current_state = _state_for_indexes(slots, active_indexes)
    active_slot = slots[active_indexes[0]].as_dict() if len(active_indexes) == 1 else None

    base = now.replace(second=0, microsecond=0)
    next_change: datetime | None = None
    next_period: str | None = None

    for delta in range(1, MINUTES_PER_WEEK + 1):
        candidate_state = _state_for_indexes(
            slots,
            coverage[(current_minute + delta) % MINUTES_PER_WEEK],
        )
        if candidate_state != current_state:
            next_change = base + timedelta(minutes=delta)
            next_period = candidate_state
            break

    return TariffPeriodStatus(
        state=current_state,
        active_slot=active_slot,
        next_change=next_change,
        next_period=next_period,
        conflict=conflict,
        valid=True,
    )
