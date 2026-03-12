"""Fixture boundary for BA runner tests and canned run data."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from pydantic import Field

from .models import BAModel

MODULE_PURPOSE = "Own deterministic BA fixtures and fixture-loading helpers used by tests."

OWNS = (
    "Fixture metadata and loaders",
    "Shared canned inputs for extraction/rendering/validation tests",
    "Test-only helpers that should not leak into runtime MCP modules",
)

MUST_NOT_OWN = (
    "Production prompt text",
    "Live NotebookLM calls",
    "MCP server wiring",
    "Rendered bundle business logic",
)

DEFAULT_FIXTURE_ROOT = Path("tests/fixtures/ba")


class FixtureScenario(str, Enum):
    CLEAN_FEATURE = "clean_feature"
    MISSING_CONTRACT = "missing_contract"
    CONTRADICTORY_SOURCES = "contradictory_sources"
    GARBLED_PDF = "garbled_pdf"
    RERUN_DIFF = "rerun_diff"
    NOTE_CLARIFICATION = "note_clarification"


SCENARIO_DESCRIPTIONS: dict[FixtureScenario, str] = {
    FixtureScenario.CLEAN_FEATURE: "Stable BA source set with a clean contract path.",
    FixtureScenario.MISSING_CONTRACT: "BA requirements are present but backend contract detail is absent.",
    FixtureScenario.CONTRADICTORY_SOURCES: "Primary and supporting sources disagree in material ways.",
    FixtureScenario.GARBLED_PDF: "Scanned or low-quality BA source intended to trigger degradation.",
    FixtureScenario.RERUN_DIFF: "Before/after source materials for impacted-screen rerun testing.",
    FixtureScenario.NOTE_CLARIFICATION: "Note-derived clarification sources that stay distinct from primary BA inputs.",
}


class FixtureManifest(BAModel):
    scenario: FixtureScenario
    description: str = Field(min_length=1)
    sources_dir: str
    notes_dir: str
    expected_dir: str
    before_dir: str | None = None
    after_dir: str | None = None


@dataclass(frozen=True)
class FixturePaths:
    root: Path
    sources_dir: Path
    notes_dir: Path
    expected_dir: Path
    manifest_json: Path
    before_dir: Path | None = None
    after_dir: Path | None = None


@dataclass(frozen=True)
class RerunDiffFixtureData:
    layout: FixturePaths
    manifest: FixtureManifest
    before_text_by_source: dict[str, str]
    after_text_by_source: dict[str, str]
    expected_impacted_screens_json: str
    expected_changelog_markdown: str


@dataclass(frozen=True)
class FixturePackageData:
    layout: FixturePaths
    manifest: FixtureManifest
    source_text_by_name: dict[str, str]
    note_text_by_name: dict[str, str]
    expected_text_by_name: dict[str, str]
    before_text_by_name: dict[str, str] = field(default_factory=dict)
    after_text_by_name: dict[str, str] = field(default_factory=dict)


def fixture_root(workspace_root: Path | str = Path(".")) -> Path:
    return Path(workspace_root).resolve() / DEFAULT_FIXTURE_ROOT


def fixture_paths(
    scenario: FixtureScenario,
    *,
    workspace_root: Path | str = Path("."),
) -> FixturePaths:
    root = fixture_root(workspace_root) / scenario.value
    before_dir = root / "before" if scenario is FixtureScenario.RERUN_DIFF else None
    after_dir = root / "after" if scenario is FixtureScenario.RERUN_DIFF else None
    return FixturePaths(
        root=root,
        sources_dir=root / "sources",
        notes_dir=root / "notes",
        expected_dir=root / "expected",
        manifest_json=root / "fixture.json",
        before_dir=before_dir,
        after_dir=after_dir,
    )


def ensure_fixture_skeleton(
    *,
    workspace_root: Path | str = Path("."),
) -> dict[FixtureScenario, FixturePaths]:
    root = fixture_root(workspace_root)
    root.mkdir(parents=True, exist_ok=True)

    layouts: dict[FixtureScenario, FixturePaths] = {}
    for scenario in FixtureScenario:
        layout = fixture_paths(scenario, workspace_root=workspace_root)
        layout.root.mkdir(parents=True, exist_ok=True)
        layout.sources_dir.mkdir(parents=True, exist_ok=True)
        layout.notes_dir.mkdir(parents=True, exist_ok=True)
        layout.expected_dir.mkdir(parents=True, exist_ok=True)
        if layout.before_dir is not None:
            layout.before_dir.mkdir(parents=True, exist_ok=True)
        if layout.after_dir is not None:
            layout.after_dir.mkdir(parents=True, exist_ok=True)

        manifest = FixtureManifest(
            scenario=scenario,
            description=SCENARIO_DESCRIPTIONS[scenario],
            sources_dir=layout.sources_dir.name,
            notes_dir=layout.notes_dir.name,
            expected_dir=layout.expected_dir.name,
            before_dir=layout.before_dir.name if layout.before_dir else None,
            after_dir=layout.after_dir.name if layout.after_dir else None,
        )
        layout.manifest_json.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        layouts[scenario] = layout

    return layouts


def load_fixture_manifest(path: Path) -> FixtureManifest:
    return FixtureManifest.model_validate_json(path.read_text(encoding="utf-8"))


def load_fixture_package(
    scenario: FixtureScenario,
    *,
    workspace_root: Path | str = Path("."),
) -> FixturePackageData:
    layout = fixture_paths(scenario, workspace_root=workspace_root)
    manifest = load_fixture_manifest(layout.manifest_json)
    if manifest.scenario is not scenario:
        raise ValueError(
            f"fixture manifest {layout.manifest_json} declared {manifest.scenario.value}, "
            f"expected {scenario.value}"
        )
    return FixturePackageData(
        layout=layout,
        manifest=manifest,
        source_text_by_name=_load_text_map(layout.sources_dir),
        note_text_by_name=_load_text_map(layout.notes_dir),
        expected_text_by_name=_load_text_map(layout.expected_dir),
        before_text_by_name=_load_text_map(layout.before_dir) if layout.before_dir else {},
        after_text_by_name=_load_text_map(layout.after_dir) if layout.after_dir else {},
    )


def load_rerun_diff_fixture(
    *,
    workspace_root: Path | str = Path("."),
) -> RerunDiffFixtureData:
    package = load_fixture_package(FixtureScenario.RERUN_DIFF, workspace_root=workspace_root)
    if package.layout.before_dir is None or package.layout.after_dir is None:
        raise ValueError("rerun_diff fixture must define before/after directories")
    return RerunDiffFixtureData(
        layout=package.layout,
        manifest=package.manifest,
        before_text_by_source=package.before_text_by_name,
        after_text_by_source=package.after_text_by_name,
        expected_impacted_screens_json=package.expected_text_by_name["impacted-screens"],
        expected_changelog_markdown=package.expected_text_by_name["changelog"],
    )


def _load_text_map(directory: Path) -> dict[str, str]:
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(directory.iterdir())
        if path.is_file() and not path.name.startswith(".")
    }


__all__ = [
    "DEFAULT_FIXTURE_ROOT",
    "FixtureManifest",
    "FixturePackageData",
    "FixturePaths",
    "FixtureScenario",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "RerunDiffFixtureData",
    "SCENARIO_DESCRIPTIONS",
    "ensure_fixture_skeleton",
    "fixture_paths",
    "fixture_root",
    "load_fixture_manifest",
    "load_fixture_package",
    "load_rerun_diff_fixture",
]
