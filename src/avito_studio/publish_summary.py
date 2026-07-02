"""Сводка «что уедет на сервер» перед публикацией.

После каждой успешной публикации сохраняем снапшот (config.yaml + avito-descriptions/) в папку
профиля пользователя; перед следующей публикацией сравниваем текущие файлы со снапшотом и
показываем человекочитаемый список изменений. Git для этого не используется сознательно:
локальный checkout avito-bridge — рабочий репозиторий владельца, его историю трогать нельзя,
а diff к последнему коммиту врал бы после первой же публикации без коммита."""
from __future__ import annotations
import json
import shutil
from pathlib import Path
from ruamel.yaml import YAML

_yaml = YAML(typ="safe")

DEFAULT_SNAPSHOT_DIR = Path.home() / ".avito-studio" / "publish-snapshot"


def _load_catalog(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    data = _yaml.load(config_path.read_text(encoding="utf-8")) or {}
    return data.get("catalog") or {}


def _descriptions(dir_path: Path) -> dict[str, str]:
    """{series_key: text} по manifest.json (несуществующие файлы — пустой текст)."""
    manifest = dir_path / "manifest.json"
    if not manifest.exists():
        return {}
    result = {}
    for series_key, fname in json.loads(manifest.read_text(encoding="utf-8")).items():
        f = dir_path / fname
        result[series_key] = f.read_text(encoding="utf-8").strip() if f.exists() else ""
    return result


def save_snapshot(bridge_root: Path, snapshot_dir: Path) -> None:
    """Зовётся ПОСЛЕ успешной публикации: снапшот = «что сейчас на сервере»."""
    snapshot_dir = Path(snapshot_dir)
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    (snapshot_dir / "config").mkdir(parents=True)
    shutil.copy2(Path(bridge_root) / "config" / "config.yaml", snapshot_dir / "config" / "config.yaml")
    src_desc = Path(bridge_root) / "avito-descriptions"
    if src_desc.exists():
        shutil.copytree(src_desc, snapshot_dir / "avito-descriptions")


def summarize_changes(bridge_root: Path, snapshot_dir: Path) -> list[str] | None:
    """Список строк «что изменилось с прошлой публикации»; None — снапшота ещё нет
    (первая публикация из студии, базы для сравнения нет)."""
    snapshot_dir = Path(snapshot_dir)
    old_cfg_path = snapshot_dir / "config" / "config.yaml"
    if not old_cfg_path.exists():
        return None
    old = _load_catalog(old_cfg_path)
    new = _load_catalog(Path(bridge_root) / "config" / "config.yaml")
    lines: list[str] = []

    old_sel, new_sel = set(old.get("selected_series") or []), set(new.get("selected_series") or [])
    lines += [f"включена публикация: {k}" for k in sorted(new_sel - old_sel)]
    lines += [f"выключена публикация: {k}" for k in sorted(old_sel - new_sel)]

    old_force, new_force = old.get("force_include") or {}, new.get("force_include") or {}
    for nc in sorted(set(new_force) - set(old_force)):
        lines.append(f"новый товар вручную: {nc} — {new_force[nc].get('price')} ₽")
    for nc in sorted(set(new_force) & set(old_force)):
        if new_force[nc].get("price") != old_force[nc].get("price"):
            lines.append(f"цена (под заказ) {nc}: {old_force[nc].get('price')} → {new_force[nc].get('price')} ₽")
    for nc in sorted(set(old_force) - set(new_force)):
        lines.append(f"убран товар вручную: {nc}")

    old_p, new_p = old.get("manual_price_override") or {}, new.get("manual_price_override") or {}
    for nc in sorted(set(new_p) - set(old_p)):
        lines.append(f"ручная цена {nc}: {new_p[nc]} ₽")
    for nc in sorted(set(new_p) & set(old_p)):
        if new_p[nc] != old_p[nc]:
            lines.append(f"ручная цена {nc}: {old_p[nc]} → {new_p[nc]} ₽")
    for nc in sorted(set(old_p) - set(new_p)):
        lines.append(f"цена {nc}: возврат к авторасчёту")

    old_ph, new_ph = old.get("manual_photos") or {}, new.get("manual_photos") or {}
    for nc in sorted(set(new_ph) - set(old_ph)):
        lines.append(f"новое фото: {nc}")
    for nc in sorted(set(new_ph) & set(old_ph)):
        if new_ph[nc] != old_ph[nc]:
            lines.append(f"заменено фото: {nc}")

    old_b, new_b = old.get("manual_card_brief") or {}, new.get("manual_card_brief") or {}
    for nc in sorted(set(new_b) - set(old_b)):
        lines.append(f"УТП карточки: {nc}")
    for nc in sorted(set(new_b) & set(old_b)):
        if new_b[nc] != old_b[nc]:
            lines.append(f"изменено УТП: {nc}")
    for nc in sorted(set(old_b) - set(new_b)):
        lines.append(f"УТП {nc}: возврат к автотексту")

    old_d = _descriptions(snapshot_dir / "avito-descriptions")
    new_d = _descriptions(Path(bridge_root) / "avito-descriptions")
    for key in sorted(set(new_d) - set(old_d)):
        lines.append(f"описание объявления: {key}")
    for key in sorted(set(new_d) & set(old_d)):
        if new_d[key] != old_d[key]:
            lines.append(f"изменено описание: {key}")

    return lines
