"""Install and safely upgrade the mutable workspace bundled with Studio.

The executable contains only configuration templates, profile templates and
human-written descriptions.  Supplier exports are deliberately not installed:
they are operational data and must be imported by the user or obtained from
the configured source.

Upgrades are additive.  A newer template may add files or missing YAML keys,
but it never replaces an existing scalar, sequence or mapping chosen by the
user.  The complete workspace is prepared in a sibling directory and swapped
into place only after it has been validated, so a failed upgrade can restore
the previous directory unchanged.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from avito_studio.atomic_io import atomic_write_json, atomic_write_yaml

WORKSPACE_SCHEMA_VERSION = 1
WORKSPACE_TEMPLATE_VERSION = "0.3.0"
WORKSPACE_MANIFEST = ".avito-studio-workspace.json"

# Keep this allow-list intentionally narrow.  In particular, ``data`` must not
# be added here: it can contain supplier exports and other customer data.
MANAGED_DIRECTORIES = ("config", "profiles", "avito-descriptions")
RUNTIME_DIRECTORIES = ("feed_out", "state", "runtime")
_YAML_SUFFIXES = {".yaml", ".yml"}


class WorkspaceUpgradeError(RuntimeError):
    """The workspace could not be installed or upgraded safely."""


def ensure_workspace(
    template: str | Path,
    destination: str | Path,
    *,
    schema_version: int = WORKSPACE_SCHEMA_VERSION,
    template_version: str = WORKSPACE_TEMPLATE_VERSION,
) -> Path:
    """Install or additively upgrade a per-user Bridge workspace.

    A manifest with the applied schema and template version makes normal
    repeated launches a true no-op.  A legacy workspace without a manifest is
    treated as schema 0 and upgraded as long as it has ``config/config.yaml``.
    """
    source = Path(template).resolve()
    target = Path(destination).resolve()
    _validate_template(source)
    if schema_version < 1:
        raise ValueError("Workspace schema version must be positive")
    if not str(template_version).strip():
        raise ValueError("Workspace template version must not be empty")

    if target.exists():
        _validate_workspace(target)
        current = _read_manifest(target)
        if _is_current(current, schema_version, str(template_version)):
            return target
        current_schema = int(current.get("schema_version", 0))
        if current_schema > schema_version:
            # Opening a workspace produced by a newer Studio is safe; trying to
            # "upgrade" it with older defaults is not.
            return target
        return _upgrade_existing(
            source,
            target,
            schema_version=schema_version,
            template_version=str(template_version),
        )

    return _install_new(
        source,
        target,
        schema_version=schema_version,
        template_version=str(template_version),
    )


def _install_new(
    source: Path,
    target: Path,
    *,
    schema_version: int,
    template_version: str,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".bridge-install-", dir=target.parent
    ) as raw_transaction:
        staged = Path(raw_transaction) / "workspace"
        _build_fresh_workspace(source, staged)
        _write_manifest(staged, schema_version, template_version)
        _validate_workspace(staged)
        try:
            os.replace(staged, target)
        except OSError:
            # Two first launches can race.  Accept the winner only if it
            # produced a complete workspace; otherwise surface the failure.
            if target.exists():
                _validate_workspace(target)
                return target
            raise
    return target


def _upgrade_existing(
    source: Path,
    target: Path,
    *,
    schema_version: int,
    template_version: str,
) -> Path:
    # Keep the last-known-good directory outside TemporaryDirectory.  If both
    # promotion and rollback fail (for example because the disk disappears),
    # the transaction cleanup must not erase the only recoverable copy.
    previous = target.with_name(
        f".{target.name}.previous-{uuid.uuid4().hex}"
    )
    with tempfile.TemporaryDirectory(
        prefix=".bridge-upgrade-", dir=target.parent
    ) as raw_transaction:
        transaction = Path(raw_transaction)
        staged = transaction / "workspace"
        shutil.copytree(target, staged)
        _merge_template(source, staged)
        for name in RUNTIME_DIRECTORIES:
            (staged / name).mkdir(parents=True, exist_ok=True)
        _write_manifest(staged, schema_version, template_version)
        _validate_workspace(staged)

        os.replace(target, previous)
        try:
            os.replace(staged, target)
        except BaseException as upgrade_error:
            try:
                os.replace(previous, target)
            except BaseException as rollback_error:
                raise WorkspaceUpgradeError(
                    "Workspace upgrade and rollback both failed; the previous "
                    f"workspace remains at {previous}"
                ) from rollback_error
            raise WorkspaceUpgradeError(
                "Workspace upgrade failed; previous files were restored"
            ) from upgrade_error
    # Promotion succeeded.  A cleanup failure is harmless: retaining an extra
    # last-known-good copy is safer than turning a successful upgrade into an
    # apparent failure.
    shutil.rmtree(previous, ignore_errors=True)
    return target


def _build_fresh_workspace(source: Path, staged: Path) -> None:
    staged.mkdir(parents=True)
    for name in MANAGED_DIRECTORIES:
        source_directory = source / name
        if source_directory.is_dir():
            shutil.copytree(source_directory, staged / name)
    for name in RUNTIME_DIRECTORIES:
        (staged / name).mkdir()


def _merge_template(source: Path, staged: Path) -> None:
    for directory_name in MANAGED_DIRECTORIES:
        source_directory = source / directory_name
        if not source_directory.is_dir():
            continue
        destination_directory = staged / directory_name
        destination_directory.mkdir(parents=True, exist_ok=True)
        for source_item in sorted(source_directory.rglob("*")):
            relative = source_item.relative_to(source_directory)
            destination_item = destination_directory / relative
            if source_item.is_dir():
                destination_item.mkdir(parents=True, exist_ok=True)
                continue
            if not source_item.is_file():
                continue
            if not destination_item.exists():
                destination_item.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_item, destination_item)
                continue
            if destination_item.is_dir():
                raise WorkspaceUpgradeError(
                    f"Template file conflicts with a user directory: {relative}"
                )
            if (
                directory_name in {"config", "profiles"}
                and source_item.suffix.lower() in _YAML_SUFFIXES
            ):
                _merge_yaml_file(source_item, destination_item)
            elif (
                directory_name == "avito-descriptions"
                and relative.as_posix() == "manifest.json"
            ):
                _merge_description_manifest(source_item, destination_item)


def _merge_yaml_file(template_path: Path, user_path: Path) -> None:
    yaml = _round_trip_yaml()
    template_data = yaml.load(template_path.read_text(encoding="utf-8"))
    user_data = yaml.load(user_path.read_text(encoding="utf-8"))
    if not isinstance(template_data, Mapping) or not isinstance(
        user_data, MutableMapping
    ):
        return
    if _merge_missing(user_data, template_data):
        atomic_write_yaml(user_path, user_data, yaml)


def _merge_description_manifest(template_path: Path, user_path: Path) -> None:
    """Add bundled description keys without replacing user mappings."""
    try:
        template_data = json.loads(template_path.read_text(encoding="utf-8"))
        user_data = json.loads(user_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkspaceUpgradeError(
            "Description manifest is unreadable during workspace upgrade"
        ) from exc
    if not isinstance(template_data, dict) or not isinstance(user_data, dict):
        raise WorkspaceUpgradeError(
            "Description manifest must contain a JSON object"
        )
    changed = False
    for key, filename in template_data.items():
        if not isinstance(key, str) or not isinstance(filename, str):
            raise WorkspaceUpgradeError(
                "Bundled description manifest contains an invalid entry"
            )
        if key not in user_data:
            user_data[key] = filename
            changed = True
    if changed:
        atomic_write_json(user_path, user_data)


def _merge_missing(user: MutableMapping[Any, Any], template: Mapping[Any, Any]) -> bool:
    changed = False
    for key, template_value in template.items():
        if key not in user:
            user[key] = copy.deepcopy(template_value)
            changed = True
            continue
        user_value = user[key]
        if isinstance(user_value, MutableMapping) and isinstance(
            template_value, Mapping
        ):
            changed = _merge_missing(user_value, template_value) or changed
    return changed


def _write_manifest(root: Path, schema_version: int, template_version: str) -> None:
    atomic_write_json(
        root / WORKSPACE_MANIFEST,
        {
            "schema_version": schema_version,
            "template_version": template_version,
            "managed_directories": list(MANAGED_DIRECTORIES),
        },
    )


def _read_manifest(root: Path) -> dict[str, Any]:
    path = root / WORKSPACE_MANIFEST
    if not path.exists():
        return {"schema_version": 0, "template_version": "legacy"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkspaceUpgradeError(f"Workspace manifest is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise WorkspaceUpgradeError(f"Workspace manifest is invalid: {path}")
    schema = value.get("schema_version")
    version = value.get("template_version")
    if (
        not isinstance(schema, int)
        or isinstance(schema, bool)
        or schema < 0
        or not isinstance(version, str)
        or not version.strip()
    ):
        raise WorkspaceUpgradeError(f"Workspace manifest is invalid: {path}")
    return value


def _is_current(
    manifest: Mapping[str, Any],
    schema_version: int,
    template_version: str,
) -> bool:
    return (
        manifest.get("schema_version") == schema_version
        and manifest.get("template_version") == template_version
    )


def _validate_template(root: Path) -> None:
    if not root.is_dir() or not (root / "config" / "config.yaml").is_file():
        raise WorkspaceUpgradeError(
            f"Bundled Bridge template is incomplete: {root}"
        )


def _validate_workspace(root: Path) -> None:
    if not root.is_dir() or not (root / "config" / "config.yaml").is_file():
        raise WorkspaceUpgradeError(f"Bridge workspace is incomplete: {root}")


def _round_trip_yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml
