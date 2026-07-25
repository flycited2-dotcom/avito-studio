"""Profile-owned editing of the global Avito description manifest.

The Bridge runtime intentionally keeps one ``manifest.json`` because the
renderer consumes a single mapping.  Studio additionally keeps local
ownership/pending metadata.  A publication can therefore send only the
selected profile's upserts and tombstones instead of accidentally replacing
descriptions edited for another business.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from avito_studio.atomic_io import atomic_write_json, atomic_write_text

_MANIFEST_REL = Path("avito-descriptions") / "manifest.json"
_STATE_REL = Path("avito-descriptions") / ".studio-profile-state.json"
_STATE_SCHEMA = 1
_DEFAULT_PROFILE = "conditioners"
_PROFILE_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
_MAX_DESCRIPTION_BYTES = 128 * 1024


def slugify(series_key: str) -> str:
    """Return a readable, bounded and collision-safe filename."""
    slug = re.sub(r"[^a-zа-яё0-9]+", "-", series_key.lower()).strip("-")
    slug = (slug or "description")[:72].rstrip("-")
    digest = hashlib.sha256(series_key.encode("utf-8")).hexdigest()[:12]
    return f"studio-{slug}-{digest}.txt"


def _profile_key(profile: Any = None) -> str:
    value = _DEFAULT_PROFILE if profile is None else getattr(profile, "key", profile)
    value = str(value or "").strip()
    if not _PROFILE_RE.fullmatch(value):
        raise ValueError(f"Некорректный профиль описания: {value!r}")
    return value


def _manifest_path(bridge_root: Path) -> Path:
    return Path(bridge_root) / _MANIFEST_REL


def _state_path(bridge_root: Path) -> Path:
    return Path(bridge_root) / _STATE_REL


def _load_manifest(manifest_path: Path) -> dict[str, str]:
    if not manifest_path.exists():
        return {}
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("manifest.json должен содержать JSON-объект")
    result: dict[str, str] = {}
    for key, filename in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError("Ключи manifest.json должны быть непустыми строками")
        _description_path(manifest_path, filename)
        result[key] = filename
    return result


def _description_path(manifest_path: Path, fname: str) -> Path:
    if not isinstance(fname, str) or not fname:
        raise ValueError("Некорректное имя файла описания в manifest.json")
    root = manifest_path.parent.resolve()
    candidate = (manifest_path.parent / fname).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError("Путь описания выходит за пределы avito-descriptions") from None
    if Path(fname).name != fname or not fname.lower().endswith(".txt"):
        raise ValueError("Некорректное имя файла описания в manifest.json")
    if candidate == root:
        raise ValueError("Некорректное имя файла описания в manifest.json")
    return candidate


def _legacy_state(manifest: Mapping[str, str]) -> dict[str, Any]:
    """Treat the pre-profile Studio manifest as conditioners-owned.

    Before multi-business support every editable description belonged to the
    original conditioners profile.  Keeping that explicit migration rule
    prevents those existing local edits from silently disappearing.
    """
    pending: dict[str, Any] = {}
    if manifest:
        pending[_DEFAULT_PROFILE] = {
            "upserts": dict(manifest),
            "deletions": [],
        }
    return {
        "schema_version": _STATE_SCHEMA,
        "owners": {key: _DEFAULT_PROFILE for key in manifest},
        "pending": pending,
    }


def _load_state(bridge_root: Path, manifest: Mapping[str, str]) -> dict[str, Any]:
    path = _state_path(bridge_root)
    if not path.exists():
        return _legacy_state(manifest)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != _STATE_SCHEMA:
        raise ValueError("Некорректная версия реестра профилей описаний")
    owners = raw.get("owners")
    pending = raw.get("pending")
    if not isinstance(owners, dict) or not isinstance(pending, dict):
        raise ValueError("Некорректный реестр профилей описаний")

    clean_owners: dict[str, str] = {}
    for key, profile in owners.items():
        if not isinstance(key, str) or not key:
            raise ValueError("Некорректный ключ владельца описания")
        clean_owners[key] = _profile_key(profile)

    clean_pending: dict[str, dict[str, Any]] = {}
    for profile, patch in pending.items():
        profile_key = _profile_key(profile)
        if not isinstance(patch, dict):
            raise ValueError("Некорректный профильный патч описаний")
        upserts = patch.get("upserts", {})
        deletions = patch.get("deletions", [])
        if not isinstance(upserts, dict) or not isinstance(deletions, list):
            raise ValueError("Некорректный профильный патч описаний")
        clean_upserts: dict[str, str] = {}
        for key, filename in upserts.items():
            if not isinstance(key, str) or not key:
                raise ValueError("Некорректный ключ профильного патча")
            _description_path(_manifest_path(bridge_root), filename)
            clean_upserts[key] = filename
        clean_deletions: list[str] = []
        for key in deletions:
            if not isinstance(key, str) or not key:
                raise ValueError("Некорректный tombstone профильного патча")
            if key in clean_upserts:
                raise ValueError("Ключ не может одновременно обновляться и удаляться")
            clean_deletions.append(key)
        if clean_upserts or clean_deletions:
            clean_pending[profile_key] = {
                "upserts": clean_upserts,
                "deletions": sorted(set(clean_deletions)),
            }

    # A manifest may have been edited by an older Studio after this metadata
    # was first created.  Such legacy keys retain the historical conditioners
    # ownership and remain pending until a confirmed publication.
    legacy_patch = clean_pending.setdefault(
        _DEFAULT_PROFILE, {"upserts": {}, "deletions": []}
    )
    for key, filename in manifest.items():
        if key not in clean_owners:
            clean_owners[key] = _DEFAULT_PROFILE
            legacy_patch["upserts"][key] = filename
    if not legacy_patch["upserts"] and not legacy_patch["deletions"]:
        clean_pending.pop(_DEFAULT_PROFILE, None)

    return {
        "schema_version": _STATE_SCHEMA,
        "owners": clean_owners,
        "pending": clean_pending,
    }


def _restore_text_files(originals: Mapping[Path, str | None]) -> None:
    for path, original in reversed(list(originals.items())):
        if original is None:
            path.unlink(missing_ok=True)
        else:
            # Use the text primitive for rollback even when atomic_write_json
            # itself is the failed/injected operation.
            atomic_write_text(path, original)


def _commit_change(
    *,
    manifest_path: Path,
    manifest: Mapping[str, str],
    state_path: Path,
    state: Mapping[str, Any],
    description_write: tuple[Path, str] | None = None,
    description_delete: Path | None = None,
) -> None:
    paths = [manifest_path, state_path]
    if description_write is not None:
        paths.insert(0, description_write[0])
    if description_delete is not None and description_delete not in paths:
        paths.append(description_delete)
    originals = {
        path: path.read_text(encoding="utf-8") if path.exists() else None
        for path in paths
    }
    try:
        if description_write is not None:
            atomic_write_text(description_write[0], description_write[1])
        atomic_write_json(manifest_path, dict(manifest))
        atomic_write_json(state_path, dict(state))
        if description_delete is not None:
            description_delete.unlink(missing_ok=True)
    except BaseException:
        _restore_text_files(originals)
        raise


def get_description(
    bridge_root: Path,
    series_key: str,
    profile: Any = None,
) -> str:
    manifest_path = _manifest_path(bridge_root)
    manifest = _load_manifest(manifest_path)
    fname = manifest.get(series_key)
    if not fname:
        return ""
    if profile is not None:
        profile_key = _profile_key(profile)
        owner = _load_state(bridge_root, manifest)["owners"].get(series_key)
        if owner is not None and owner != profile_key:
            return ""
    path = _description_path(manifest_path, fname)
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def save_description(
    bridge_root: Path,
    series_key: str,
    text: str,
    profile: Any = None,
) -> None:
    """Save an override and record an owner-scoped pending upsert/tombstone."""
    if not isinstance(series_key, str) or not series_key or len(series_key) > 1024:
        raise ValueError("Некорректный ключ серии")
    profile_key = _profile_key(profile)
    manifest_path = _manifest_path(bridge_root)
    manifest = _load_manifest(manifest_path)
    state = _load_state(bridge_root, manifest)
    owner = state["owners"].get(series_key)
    if owner is not None and owner != profile_key:
        raise ValueError(
            f"Описание {series_key!r} принадлежит профилю {owner!r}, "
            f"а не {profile_key!r}"
        )

    normalized = str(text).strip()
    if not normalized:
        _remove_description(
            Path(bridge_root), manifest_path, manifest, state, series_key, profile_key
        )
        return
    encoded = normalized.encode("utf-8")
    if len(encoded) > _MAX_DESCRIPTION_BYTES:
        raise ValueError("Описание превышает безопасный лимит 128 КиБ")

    fname = manifest.get(series_key) or slugify(series_key)
    if any(key != series_key and other == fname for key, other in manifest.items()):
        fname = slugify(series_key)
    description_path = _description_path(manifest_path, fname)
    manifest[series_key] = fname
    state["owners"][series_key] = profile_key
    patch = state["pending"].setdefault(
        profile_key, {"upserts": {}, "deletions": []}
    )
    patch["upserts"][series_key] = fname
    patch["deletions"] = [key for key in patch["deletions"] if key != series_key]
    _commit_change(
        manifest_path=manifest_path,
        manifest=manifest,
        state_path=_state_path(bridge_root),
        state=state,
        description_write=(description_path, normalized + "\n"),
    )


def delete_description(
    bridge_root: Path,
    series_key: str,
    profile: Any = None,
) -> bool:
    """Remove an override and retain a profile-owned publication tombstone."""
    profile_key = _profile_key(profile)
    manifest_path = _manifest_path(bridge_root)
    manifest = _load_manifest(manifest_path)
    state = _load_state(bridge_root, manifest)
    return _remove_description(
        Path(bridge_root), manifest_path, manifest, state, series_key, profile_key
    )


def _remove_description(
    bridge_root: Path,
    manifest_path: Path,
    manifest: dict[str, str],
    state: dict[str, Any],
    series_key: str,
    profile_key: str,
) -> bool:
    fname = manifest.get(series_key)
    if not fname:
        return False
    owner = state["owners"].get(series_key)
    if owner is not None and owner != profile_key:
        raise ValueError(
            f"Описание {series_key!r} принадлежит профилю {owner!r}, "
            f"а не {profile_key!r}"
        )
    description_path = _description_path(manifest_path, fname)
    del manifest[series_key]
    state["owners"][series_key] = profile_key
    patch = state["pending"].setdefault(
        profile_key, {"upserts": {}, "deletions": []}
    )
    patch["upserts"].pop(series_key, None)
    patch["deletions"] = sorted(set([*patch["deletions"], series_key]))
    delete_file = (
        description_path if fname not in manifest.values() else None
    )
    _commit_change(
        manifest_path=manifest_path,
        manifest=manifest,
        state_path=_state_path(bridge_root),
        state=state,
        description_delete=delete_file,
    )
    return True


def build_profile_patch(
    bridge_root: Path,
    profile: Any = None,
) -> dict[str, Any]:
    """Return the selected profile's validated pending publication patch."""
    profile_key = _profile_key(profile)
    manifest_path = _manifest_path(bridge_root)
    manifest = _load_manifest(manifest_path)
    state = _load_state(bridge_root, manifest)
    raw = state["pending"].get(
        profile_key, {"upserts": {}, "deletions": []}
    )
    upserts: dict[str, str] = {}
    file_hashes: dict[str, str] = {}
    for key, filename in raw["upserts"].items():
        if state["owners"].get(key) != profile_key:
            raise ValueError(f"Профиль {profile_key!r} не владеет описанием {key!r}")
        if manifest.get(key) != filename:
            raise ValueError(f"Профильный патч {key!r} не совпадает с manifest.json")
        path = _description_path(manifest_path, filename)
        if not path.is_file():
            raise FileNotFoundError(f"Файл описания не найден: {path}")
        if path.stat().st_size > _MAX_DESCRIPTION_BYTES:
            raise ValueError(f"Файл описания слишком большой: {path.name}")
        if not path.read_text(encoding="utf-8").strip():
            raise ValueError(f"Файл описания пуст: {path.name}")
        upserts[key] = filename
        file_hashes[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
    deletions = sorted(set(raw["deletions"]))
    for key in deletions:
        if state["owners"].get(key) != profile_key:
            raise ValueError(
                f"Профиль {profile_key!r} не владеет tombstone {key!r}"
            )
    return {
        "schema_version": 1,
        "profile": profile_key,
        "upserts": dict(sorted(upserts.items())),
        "deletions": deletions,
        "files_sha256": dict(sorted(file_hashes.items())),
    }


def acknowledge_profile_patch(
    bridge_root: Path,
    profile: Any,
    published_patch: Mapping[str, Any],
) -> bool:
    """Clear only the exact patch confirmed by the remote publisher.

    If the user edited the same profile while an upload was in flight, the
    current patch differs and remains pending for the next publication.
    """
    profile_key = _profile_key(profile)
    current = build_profile_patch(bridge_root, profile_key)
    if current != dict(published_patch):
        return False
    manifest = _load_manifest(_manifest_path(bridge_root))
    state = _load_state(bridge_root, manifest)
    state["pending"].pop(profile_key, None)
    atomic_write_json(_state_path(bridge_root), deepcopy(state))
    return True
