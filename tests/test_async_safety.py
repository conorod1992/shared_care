"""Static regressions for calls that must not run on Home Assistant's event loop."""

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "shared_schedule"


def test_holiday_calendar_is_only_passed_to_executor() -> None:
    """The holidays registry lazily imports country modules and can block."""
    executor_calls = 0
    direct_calls = []

    for filename in ("config_flow.py", "coordinator.py"):
        tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if node.func.attr == "async_add_executor_job":
                executor_calls += 1
            if node.func.attr == "country_holidays":
                direct_calls.append((filename, node.lineno))

    assert executor_calls >= 2
    assert direct_calls == []
