"""Migrations of saved data to the current schema.

Saved workspaces (storage.py) and Grill interviews (grill/persistence.py) are
JSON files that outlive app versions. Each loader passes the raw JSON through
the matching `migrate_*` function before validating it, so older saves keep
opening. Migrations only add what a newer schema needs; they never change or
drop the user's data, and an unknown (newer) version is refused, not guessed.

Workspace versions:
- 1: everything before the version field existed (no `schema_version` key).
- 2: `finding_history` (status changes of findings). Findings that a v1 save
  already marks resolved keep their status; their earlier history is simply
  not known, and nothing is made up for it.

Grill session versions are handled in grill/models.py (`migrate_session_data`).
"""

from typing import Any

from spec_to_test.models import WORKSPACE_SCHEMA_VERSION


class MigrationError(ValueError):
    """The data has a schema this version of the app does not know."""


def workspace_version(data: dict[str, Any]) -> int:
    version = data.get("schema_version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise MigrationError(f"invalid workspace schema: {version!r}")
    return version


def migrate_workspace_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a saved workspace upgraded to WORKSPACE_SCHEMA_VERSION."""
    if not isinstance(data, dict):
        raise MigrationError("a workspace must be a JSON object")
    version = workspace_version(data)
    if version > WORKSPACE_SCHEMA_VERSION:
        raise MigrationError(f"workspace schema {version} is newer than this app ({WORKSPACE_SCHEMA_VERSION})")
    data = dict(data)
    if version < 2:
        data.setdefault("finding_history", [])
        version = 2
    data["schema_version"] = version
    return data
