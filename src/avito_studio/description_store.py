"""Редактирование описаний серий: текстовые файлы avito-descriptions/*.txt + manifest.json
(series_key → имя файла). Переопределяют автогенерацию описания в render_series (см. avito-bridge
content/descriptions.py). Новые записи получают имя файла studio-{slug}.txt."""
from __future__ import annotations
import json
import re
from pathlib import Path

_MANIFEST_REL = Path("avito-descriptions") / "manifest.json"


def slugify(series_key: str) -> str:
    slug = re.sub(r"[^a-zа-я0-9]+", "-", series_key.lower()).strip("-")
    return f"studio-{slug}.txt"


def _manifest_path(bridge_root: Path) -> Path:
    return Path(bridge_root) / _MANIFEST_REL


def _load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def get_description(bridge_root: Path, series_key: str) -> str:
    manifest_path = _manifest_path(bridge_root)
    fname = _load_manifest(manifest_path).get(series_key)
    if not fname:
        return ""
    f = manifest_path.parent / fname
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def save_description(bridge_root: Path, series_key: str, text: str) -> None:
    manifest_path = _manifest_path(bridge_root)
    manifest = _load_manifest(manifest_path)
    fname = manifest.get(series_key) or slugify(series_key)
    (manifest_path.parent / fname).write_text(text.strip() + "\n", encoding="utf-8")
    manifest[series_key] = fname
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
