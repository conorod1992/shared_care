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


def test_frontend_panel_asset_is_packaged() -> None:
    panel = (
        ROOT
        / "custom_components"
        / "shared_schedule"
        / "frontend"
        / "shared-schedule-panel.js"
    )
    assert panel.is_file()
    contents = panel.read_text(encoding="utf-8")
    assert "shared_schedule/date_overrides/set" in contents
    assert "shared_schedule/party_colors/set" in contents
    assert "Override ·" in contents


def test_date_overrides_are_loaded_and_saved_through_store() -> None:
    coordinator = (
        ROOT / "custom_components" / "shared_schedule" / "coordinator.py"
    ).read_text(encoding="utf-8")
    assert 'stored.get("date_overrides", {})' in coordinator
    assert '"date_overrides": dict(sorted(' in coordinator


def test_party_colours_are_loaded_and_saved_through_store() -> None:
    coordinator = (
        ROOT / "custom_components" / "shared_schedule" / "coordinator.py"
    ).read_text(encoding="utf-8")
    assert 'stored.get("display_settings", {})' in coordinator
    assert '"display_settings": dict(self.display_settings)' in coordinator
