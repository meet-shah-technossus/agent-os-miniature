"""Parse requirements YAML and store in the database."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from ..storage.database import Database
from ..storage.models import RequirementRecord, RequirementType
from ..storage.requirement_repo import RequirementRepository
from .schema import RequirementsDocument
from .validator import validate_requirements

logger = logging.getLogger(__name__)


def _flat_list_yaml_to_canonical(rows: list[Any]) -> tuple[bytes, dict[str, int], str]:
    """Convert a flat-list YAML (Epic / Feature / User Story / Acceptance Criteria columns)
    into the canonical RequirementsDocument dict format (epics → features → stories → ACs).

    This handles YAML files exported from spreadsheets where each row is one user story
    and the hierarchy is encoded as repeated column values rather than nesting.
    """
    epics: dict[str, dict] = {}  # epic_title → epic dict with internal _feat_map

    for row in rows:
        if not isinstance(row, dict):
            continue
        epic_title = str(row.get("Epic") or "").strip()
        feat_title = str(row.get("Feature") or "").strip()
        story_title = str(row.get("User Story") or "").strip()
        ac_raw = str(row.get("Acceptance Criteria") or "").strip()

        # Skip rows with nothing useful (e.g. the trailing empty row)
        if not epic_title and not story_title:
            continue

        if not epic_title:
            epic_title = "General"
        if not feat_title:
            feat_title = "General"

        if epic_title not in epics:
            epic_id = f"E{len(epics) + 1}"
            epics[epic_title] = {
                "id": epic_id,
                "title": epic_title,
                "description": "",
                "features": [],
                "_feat_map": {},
            }

        epic = epics[epic_title]
        feat_map: dict[str, dict] = epic["_feat_map"]

        if feat_title not in feat_map:
            feat_id = f"{epic['id']}-F{len(feat_map) + 1}"
            feat_dict: dict = {"id": feat_id, "title": feat_title, "description": "", "stories": []}
            feat_map[feat_title] = feat_dict
            epic["features"].append(feat_dict)

        if not story_title:
            continue

        feat = feat_map[feat_title]
        story_id = f"{feat['id']}-S{len(feat['stories']) + 1}"

        # Split ACs on â¢ (mis-encoded UTF-8 bullet •) or plain •
        ac_list: list[dict] = []
        if ac_raw:
            parts = [p.strip() for p in re.split(r"â¢|•", ac_raw) if p.strip()]
            for i, part in enumerate(parts, 1):
                ac_list.append({
                    "id": f"{story_id}-AC{i}",
                    "title": part,
                    "description": "",
                })

        if not ac_list:
            ac_list = [{"id": f"{story_id}-AC1", "title": "Verify the feature works as described.", "description": ""}]

        feat["stories"].append({
            "id": story_id,
            "title": story_title,
            "description": "",
            "acceptance_criteria": ac_list,
        })

    # Strip internal tracking key before serialising
    epic_list = [{k: v for k, v in ep.items() if k != "_feat_map"} for ep in epics.values()]

    if not epic_list:
        return b"", {}, "No valid requirements found in the YAML list."

    doc = {"epics": epic_list}
    yaml_bytes = yaml.dump(doc, allow_unicode=True, sort_keys=False).encode("utf-8")

    n_feats = sum(len(ep["features"]) for ep in epic_list)
    n_stories = sum(len(f["stories"]) for ep in epic_list for f in ep["features"])
    n_ac = sum(
        len(s["acceptance_criteria"])
        for ep in epic_list for f in ep["features"] for s in f["stories"]
    )
    stats = {
        "epics": len(epic_list),
        "features": n_feats,
        "stories": n_stories,
        "acceptance_criteria": n_ac,
    }
    return yaml_bytes, stats, ""


class RequirementsParser:
    """Load a requirements YAML file, validate, and persist records."""

    def __init__(self, db: Database) -> None:
        self._repo = RequirementRepository(db.conn)

    def load_and_store(self, path: str) -> dict[str, int]:
        """Parse *path*, validate, store all records, return counts."""
        raw = self._read_yaml(path)
        doc = RequirementsDocument.model_validate(raw)

        errors = validate_requirements(doc)
        if errors:
            msg = "Requirements validation failed:\n" + "\n".join(
                f"  - {e}" for e in errors
            )
            raise ValueError(msg)

        counts = {"epics": 0, "features": 0, "stories": 0, "acceptance_criteria": 0}
        for epic in doc.epics:
            self._store(epic.id, RequirementType.EPIC, None, epic.title, epic.description)
            counts["epics"] += 1
            for feat in epic.features:
                self._store(feat.id, RequirementType.FEATURE, epic.id, feat.title, feat.description)
                counts["features"] += 1
                for story in feat.stories:
                    self._store(story.id, RequirementType.STORY, feat.id, story.title, story.description)
                    counts["stories"] += 1
                    for ac in story.acceptance_criteria:
                        self._store(ac.id, RequirementType.ACCEPTANCE_CRITERIA, story.id, ac.title, ac.description)
                        counts["acceptance_criteria"] += 1

        logger.info("Stored %s requirements records.", sum(counts.values()))
        return counts

    # ------------------------------------------------------------------

    @staticmethod
    def _read_yaml(path: str) -> dict:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Requirements file not found: {path}")

        if p.suffix.lower() == ".md":
            import re as _re
            text = p.read_text(encoding="utf-8")
            match = _re.search(r"```yaml\s*\n(.*?)\n```", text, _re.DOTALL)
            if not match:
                raise ValueError(
                    f"No YAML code block found in requirements file: {path}"
                )
            data = yaml.safe_load(match.group(1))
        else:
            with p.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)

        if not isinstance(data, dict):
            if isinstance(data, list):
                canonical_bytes, _, err = _flat_list_yaml_to_canonical(data)
                if err:
                    raise ValueError(f"Cannot convert flat-list YAML to requirements format: {err}")
                data = yaml.safe_load(canonical_bytes.decode("utf-8"))
            else:
                raise ValueError(f"Requirements file must be a YAML mapping, got {type(data).__name__}")
        return data

    def _store(
        self,
        req_id: str,
        req_type: RequirementType,
        parent_id: str | None,
        title: str,
        description: str,
    ) -> None:
        record = RequirementRecord(
            id=req_id,
            type=req_type,
            parent_id=parent_id,
            title=title,
            description=description,
        )
        self._repo.upsert(record)
