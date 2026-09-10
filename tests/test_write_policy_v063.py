from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "dji_power_bt"


def load_policy():
    name = "custom_components.dji_power_bt.write_policy"
    spec = importlib.util.spec_from_file_location(name, ROOT / "write_policy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


policy = load_policy()


def test_off_peak_power_verification_never_forces_readback():
    item = policy.OFF_PEAK_POWER_WRITE_VERIFICATION
    assert item.allow_readback is False
    assert item.wait_for_report_s >= 10.0
    assert item.timeout_source == "passive_0x62_not_observed"


def test_active_verification_waits_for_periodic_report_before_readback():
    item = policy.ACTIVE_WRITE_VERIFICATION
    assert item.allow_readback is True
    assert item.wait_for_report_s >= 10.0


def test_snapshot_freshness_uses_device_report_age():
    assert policy.snapshot_is_fresh(
        last_report_monotonic=100.0, now_monotonic=129.9, max_age_s=30.0
    )
    assert not policy.snapshot_is_fresh(
        last_report_monotonic=100.0, now_monotonic=130.1, max_age_s=30.0
    )
    assert not policy.snapshot_is_fresh(
        last_report_monotonic=None, now_monotonic=130.0, max_age_s=30.0
    )
    assert not policy.snapshot_is_fresh(
        last_report_monotonic=131.0, now_monotonic=130.0, max_age_s=30.0
    )
