import json

from larksync.web.tasks import _extract_planned_total, _update_progress_counters


def test_extract_planned_total_prefers_total_files():
    payload = {
        "_plan_summary": {
            "total_files": 10,
            "will_download": 3,
        }
    }

    assert _extract_planned_total(payload) == 10


def test_extract_planned_total_fallback_to_will_download():
    payload = {
        "_plan_summary": {
            "will_download": 5,
        }
    }

    assert _extract_planned_total(payload) == 5


def test_extract_planned_total_from_string_payload():
    payload = {
        "_plan_summary": json.dumps({"total_files": 7})
    }

    assert _extract_planned_total(payload) == 7


def test_update_progress_counts_all_outcomes() -> None:
    runtime = {"planned_total": 3}

    completed, expected = _update_progress_counters(runtime, "plan", 0, 3)
    assert completed == 0
    assert expected == 3

    completed, expected = _update_progress_counters(runtime, "success", 1, 3)
    assert completed == 1
    assert expected == 3

    completed, expected = _update_progress_counters(runtime, "skip", 1, 3)
    assert completed == 2
    assert expected == 3

    completed, expected = _update_progress_counters(runtime, "failed", 2, 3)
    assert completed == 3
    assert expected == 3


def test_update_progress_uses_engine_counts_when_needed() -> None:
    runtime: dict[str, int] = {}

    completed, expected = _update_progress_counters(runtime, "progress", 2, 0)
    assert completed == 2
    assert expected == 2

    completed, expected = _update_progress_counters(runtime, "plan", 2, 5)
    assert completed == 2
    assert expected == 5


def test_update_progress_plan_stage_resets_zero_counts() -> None:
    runtime = {"completed": 4, "engine_processed": 4, "planned_total": 6}

    completed, expected = _update_progress_counters(runtime, "plan", 0, 3)

    assert completed == 0
    assert expected == 6

    completed, expected = _update_progress_counters(runtime, "success", 1, 3)
    assert completed == 1
    assert expected == 6
