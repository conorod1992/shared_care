"""Repository packaging checks."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_hacs_metadata_is_present() -> None:
    metadata = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert metadata["name"] == "Shared Schedule"


def test_manifest_contains_hacs_required_fields() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "shared_schedule" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    required = {
        "domain",
        "documentation",
        "issue_tracker",
        "codeowners",
        "name",
        "version",
    }
    assert required <= manifest.keys()
    assert "requirements" not in manifest


def test_frontend_panel_asset_is_packaged() -> None:
    panel = (
        ROOT
        / "custom_components"
        / "shared_schedule"
        / "frontend"
        / "shared-schedule-panel.js"
    )
    assert panel.is_file()
    assert "shared_schedule/date_overrides/set" in panel.read_text(encoding="utf-8")


def test_date_overrides_are_loaded_and_saved_through_store() -> None:
    coordinator = (
        ROOT / "custom_components" / "shared_schedule" / "coordinator.py"
    ).read_text(encoding="utf-8")
    assert 'stored.get("date_overrides", {})' in coordinator
    assert '"date_overrides": dict(sorted(' in coordinator


def test_fallback_holidays_are_loaded_and_saved_through_store() -> None:
    coordinator = (
        ROOT / "custom_components" / "shared_schedule" / "coordinator.py"
    ).read_text(encoding="utf-8")
    assert 'stored.get("fallback_holidays", [])' in coordinator
    assert '"fallback_holidays": [dict(item)' in coordinator


def test_actual_owner_entities_do_not_use_raw_cadence_state() -> None:
    status = (
        ROOT / "custom_components" / "shared_schedule" / "sensor.py"
    ).read_text(encoding="utf-8")
    binary = (
        ROOT / "custom_components" / "shared_schedule" / "binary_sensor.py"
    ).read_text(encoding="utf-8")
    assert "self.coordinator.actual_current_party" in status
    assert "self.coordinator.actual_current_party == self._party" in binary


def test_subject_name_is_optional_and_exposed_to_the_panel() -> None:
    config_flow = (
        ROOT / "custom_components" / "shared_schedule" / "config_flow.py"
    ).read_text(encoding="utf-8")
    panel_api = (
        ROOT / "custom_components" / "shared_schedule" / "frontend.py"
    ).read_text(encoding="utf-8")
    assert 'current.get(CONF_SUBJECT_NAME, "")' in config_flow
    assert '"subject_name": subject_name' in panel_api


def test_frontend_relative_time_uses_local_calendar_days() -> None:
    panel = (
        ROOT
        / "custom_components"
        / "shared_schedule"
        / "frontend"
        / "shared-schedule-panel.js"
    ).read_text(encoding="utf-8")
    assert "localCalendarDay(value) - localCalendarDay(new Date())" in panel
    assert "Math.ceil" not in panel
