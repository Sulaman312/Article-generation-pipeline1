"""Step timing helpers — UTC-only, no server-local timezone in durations."""

from datetime import datetime, timezone

from backend import artifacts


def test_duration_ms_uses_utc_for_naive_timestamps():
    start = "2026-07-12T10:00:00.000"
    end = "2026-07-12T10:02:05.500"
    assert artifacts._duration_ms(start, end) == 125500


def test_duration_ms_accepts_z_suffix():
    start = "2026-07-12T10:00:00.000Z"
    end = "2026-07-12T10:00:45.000Z"
    assert artifacts._duration_ms(start, end) == 45000


def test_patch_step_timing_records_utc_z():
    timings = artifacts.patch_step_timing({}, "outline", event="start", status="running")
    started = timings["outline"]["started_at"]
    assert started.endswith("Z")
    assert "+08:00" not in started

    finished = artifacts.patch_step_timing(
        timings, "outline", event="finish", status="done"
    )
    entry = finished["outline"]
    assert entry["finished_at"].endswith("Z")
    assert entry["duration_ms"] is not None
    assert entry["duration_ms"] >= 0


def test_normalize_step_timing_converts_naive_to_z():
    normalized = artifacts._normalize_step_timing(
        {
            "started_at": "2026-07-12T08:00:00.000",
            "finished_at": "2026-07-12T08:00:23.000",
            "duration_ms": 23000,
        }
    )
    assert normalized["started_at"] == "2026-07-12T08:00:00.000Z"
    assert normalized["finished_at"] == "2026-07-12T08:00:23.000Z"


def test_epoch_iso_is_utc():
    ts = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    assert artifacts._epoch_iso(ts) == "2026-07-12T12:00:00.000Z"
