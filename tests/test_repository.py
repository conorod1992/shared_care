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
