"""Profile-aware publication snapshots and human-readable change summaries."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

from ruamel.yaml import YAML

_yaml = YAML(typ="safe")

DEFAULT_SNAPSHOT_DIR = Path.home() / ".avito-studio" / "publish-snapshot"
_SAFE_PROFILE = re.compile(r"[A-Za-z0-9_.-]+\Z")


def _snapshot_root(snapshot_dir: Path, profile_key: str | None) -> Path:
    root = Path(snapshot_dir)
    if profile_key is None:
        return root
    if not _SAFE_PROFILE.fullmatch(profile_key):
        raise ValueError(f"Некорректный ключ профиля: {profile_key!r}")
    return root / profile_key


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    value = _yaml.load(path.read_text(encoding="utf-8")) or {}
    return value if isinstance(value, dict) else {}


def _load_catalog(config_path: Path) -> dict:
    return _load_yaml(config_path).get("catalog") or {}


def _descriptions(dir_path: Path) -> dict[str, str]:
    """Return descriptions referenced by a safe local manifest."""
    manifest = dir_path / "manifest.json"
    if not manifest.exists():
        return {}
    mapping = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict):
        return {}
    base = dir_path.resolve()
    result: dict[str, str] = {}
    for series_key, filename in mapping.items():
        if not isinstance(series_key, str) or not isinstance(filename, str):
            continue
        candidate = (base / filename).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            continue
        result[series_key] = (
            candidate.read_text(encoding="utf-8").strip()
            if candidate.is_file()
            else ""
        )
    return result


def _file_signature(path: Path) -> dict:
    if not path.is_file():
        return {"path": str(path), "exists": False}
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path),
        "exists": True,
        "size": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def _source_signature(bridge_root: Path, config_path: Path) -> dict | None:
    data = _load_yaml(config_path)
    raw_path = (
        ((data.get("profile") or {}).get("source_options") or {}).get("path")
    )
    if not raw_path:
        return None
    source = Path(str(raw_path))
    if not source.is_absolute():
        source = Path(bridge_root) / source
    return _file_signature(source.resolve())


def _atomic_replace_snapshot(staged: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_name(f".{target.name}.{uuid.uuid4().hex}.backup")
    moved_old = False
    try:
        if target.exists():
            os.replace(target, backup)
            moved_old = True
        os.replace(staged, target)
    except Exception as replace_error:
        if moved_old and backup.exists():
            if target.exists():
                raise RuntimeError(
                    "Не удалось подтвердить замену снимка публикации. "
                    f"Предыдущая версия сохранена в резервной копии: {backup}"
                ) from replace_error
            try:
                os.replace(backup, target)
            except Exception as restore_error:
                raise RuntimeError(
                    "Не удалось заменить снимок публикации и восстановить "
                    f"предыдущую версию. Резервная копия сохранена: {backup}"
                ) from restore_error
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


def save_snapshot(
    bridge_root: Path,
    snapshot_dir: Path,
    config_path: Path | None = None,
    profile_key: str | None = None,
) -> None:
    """Save exactly the profile and source which were successfully published."""
    bridge_root = Path(bridge_root)
    source_config = (
        Path(config_path)
        if config_path is not None
        else bridge_root / "config" / "config.yaml"
    )
    target = _snapshot_root(Path(snapshot_dir), profile_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{target.name}.staging-", dir=target.parent
    ) as raw_staging:
        staged = Path(raw_staging) / "snapshot"
        (staged / "config").mkdir(parents=True)
        shutil.copy2(source_config, staged / "config" / "config.yaml")
        descriptions = bridge_root / "avito-descriptions"
        if descriptions.exists():
            shutil.copytree(descriptions, staged / "avito-descriptions")
        metadata = {
            "profile_key": profile_key,
            "config_source": str(source_config.resolve()),
            "source": _source_signature(bridge_root, source_config),
        }
        (staged / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _atomic_replace_snapshot(staged, target)


def summarize_changes(
    bridge_root: Path,
    snapshot_dir: Path,
    config_path: Path | None = None,
    profile_key: str | None = None,
) -> list[str] | None:
    """Describe changes against the last successful publication of this profile."""
    bridge_root = Path(bridge_root)
    snapshot = _snapshot_root(Path(snapshot_dir), profile_key)
    current_config = (
        Path(config_path)
        if config_path is not None
        else bridge_root / "config" / "config.yaml"
    )
    old_config = snapshot / "config" / "config.yaml"
    if not old_config.exists():
        return None

    old = _load_catalog(old_config)
    new = _load_catalog(current_config)
    lines: list[str] = []

    old_full = _load_yaml(old_config)
    new_full = _load_yaml(current_config)
    if (
        {key: value for key, value in old_full.items() if key != "catalog"}
        != {key: value for key, value in new_full.items() if key != "catalog"}
    ):
        lines.append("изменены настройки профиля, источника, цены или фида")

    old_selected = set(old.get("selected_series") or [])
    new_selected = set(new.get("selected_series") or [])
    lines += [
        f"включена публикация: {key}"
        for key in sorted(new_selected - old_selected)
    ]
    lines += [
        f"выключена публикация: {key}"
        for key in sorted(old_selected - new_selected)
    ]

    old_force, new_force = old.get("force_include") or {}, new.get("force_include") or {}
    for nc_code in sorted(set(new_force) - set(old_force)):
        entry = new_force[nc_code]
        price = entry.get("price") if isinstance(entry, dict) else entry
        lines.append(f"новый товар вручную: {nc_code} — {price} ₽")
    for nc_code in sorted(set(new_force) & set(old_force)):
        old_entry, new_entry = old_force[nc_code], new_force[nc_code]
        old_price = old_entry.get("price") if isinstance(old_entry, dict) else old_entry
        new_price = new_entry.get("price") if isinstance(new_entry, dict) else new_entry
        if new_price != old_price:
            lines.append(
                f"цена (под заказ) {nc_code}: {old_price} → {new_price} ₽"
            )
    for nc_code in sorted(set(old_force) - set(new_force)):
        lines.append(f"убран товар вручную: {nc_code}")

    old_prices = old.get("manual_price_override") or {}
    new_prices = new.get("manual_price_override") or {}
    for nc_code in sorted(set(new_prices) - set(old_prices)):
        lines.append(f"ручная цена {nc_code}: {new_prices[nc_code]} ₽")
    for nc_code in sorted(set(new_prices) & set(old_prices)):
        if new_prices[nc_code] != old_prices[nc_code]:
            lines.append(
                f"ручная цена {nc_code}: "
                f"{old_prices[nc_code]} → {new_prices[nc_code]} ₽"
            )
    for nc_code in sorted(set(old_prices) - set(new_prices)):
        lines.append(f"цена {nc_code}: возврат к авторасчёту")

    old_photos, new_photos = old.get("manual_photos") or {}, new.get("manual_photos") or {}
    for nc_code in sorted(set(new_photos) - set(old_photos)):
        lines.append(f"новое фото: {nc_code}")
    for nc_code in sorted(set(new_photos) & set(old_photos)):
        if new_photos[nc_code] != old_photos[nc_code]:
            lines.append(f"заменено фото: {nc_code}")
    for nc_code in sorted(set(old_photos) - set(new_photos)):
        lines.append(f"удалено ручное фото: {nc_code}")

    old_briefs = old.get("manual_card_brief") or {}
    new_briefs = new.get("manual_card_brief") or {}
    for nc_code in sorted(set(new_briefs) - set(old_briefs)):
        lines.append(f"УТП карточки: {nc_code}")
    for nc_code in sorted(set(new_briefs) & set(old_briefs)):
        if new_briefs[nc_code] != old_briefs[nc_code]:
            lines.append(f"изменено УТП: {nc_code}")
    for nc_code in sorted(set(old_briefs) - set(new_briefs)):
        lines.append(f"УТП {nc_code}: возврат к автотексту")

    old_manual = old.get("manual_products") or {}
    new_manual = new.get("manual_products") or {}
    for manual_id in sorted(set(new_manual) - set(old_manual)):
        entry = new_manual[manual_id] or {}
        lines.append(
            f"новый полностью ручной товар: {entry.get('title') or manual_id}"
        )
    for manual_id in sorted(set(new_manual) & set(old_manual)):
        if new_manual[manual_id] != old_manual[manual_id]:
            lines.append(f"изменён полностью ручной товар: {manual_id}")
    for manual_id in sorted(set(old_manual) - set(new_manual)):
        lines.append(f"удалён полностью ручной товар: {manual_id}")

    old_descriptions = _descriptions(snapshot / "avito-descriptions")
    new_descriptions = _descriptions(bridge_root / "avito-descriptions")
    for key in sorted(set(new_descriptions) - set(old_descriptions)):
        lines.append(f"описание объявления: {key}")
    for key in sorted(set(new_descriptions) & set(old_descriptions)):
        if new_descriptions[key] != old_descriptions[key]:
            lines.append(f"изменено описание: {key}")
    for key in sorted(set(old_descriptions) - set(new_descriptions)):
        lines.append(f"удалено ручное описание: {key}")

    metadata_path = snapshot / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("source") != _source_signature(bridge_root, current_config):
            lines.append("изменён файл-источник товаров/цен")

    return lines
