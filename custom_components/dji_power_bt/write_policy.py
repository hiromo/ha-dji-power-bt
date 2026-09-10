"""Low-traffic write verification policy helpers."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WriteVerificationPolicy:
    """Describe how an acknowledged setting write is verified."""

    allow_readback: bool
    wait_for_report_s: float
    timeout_source: str


# Low-frequency controls may use one delayed 0x60 readback, but only after a full
# Power 2000 0x62 report interval has had a chance to confirm the setting.
ACTIVE_WRITE_VERIFICATION = WriteVerificationPolicy(
    allow_readback=True,
    wait_for_report_s=12.0,
    timeout_source="active_verification_timeout",
)

# Off-peak charging power can be written every 15 seconds by an automation. The
# matching 0x63 ACK completes each request; 0x62 is passive confirmation only.
OFF_PEAK_POWER_WRITE_VERIFICATION = WriteVerificationPolicy(
    allow_readback=False,
    wait_for_report_s=20.0,
    timeout_source="passive_0x62_not_observed",
)


def snapshot_is_fresh(
    *,
    last_report_monotonic: float | None,
    now_monotonic: float,
    max_age_s: float,
) -> bool:
    """Return whether a device-reported configuration snapshot is recent enough."""
    if last_report_monotonic is None or max_age_s < 0:
        return False
    age = now_monotonic - last_report_monotonic
    return 0.0 <= age <= max_age_s
