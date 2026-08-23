"""Static regressions for calls that must not run on Home Assistant's event loop."""

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "shared_schedule"


def test_optional_holiday_calendar_is_only_resolved_in_executor() -> None:
    """The holidays registry lazily imports country modules and can block."""
    coordinator = ast.parse((ROOT / "coordinator.py").read_text(encoding="utf-8"))
    executor_jobs = [
        node
        for node in ast.walk(coordinator)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "async_add_executor_job"
    ]
    assert len(executor_jobs) == 1
    assert isinstance(executor_jobs[0].args[0], ast.Name)
    assert executor_jobs[0].args[0].id == "resolve_holiday_provider"

    config_flow = (ROOT / "config_flow.py").read_text(encoding="utf-8")
    assert "holidays" not in config_flow
    assert "_async_validate_country" not in config_flow
