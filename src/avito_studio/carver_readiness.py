"""Pre-publish validation for the local CARVER price profile."""
from __future__ import annotations

from pathlib import Path

import yaml

from avito_bridge.config import load_config


def carver_publish_issues(config_path: Path, rows) -> list[str]:
    """Return user-facing blockers that would make a CARVER feed unsafe to publish."""
    cfg = load_config(Path(config_path))
    issues: list[str] = []

    selected_rows = [row for row in rows if row.selected]
    if not rows:
        issues.append("Обновите каталог CARVER, чтобы приложение видело строки прайса.")
    elif not selected_rows:
        issues.append("Выберите хотя бы одну позицию CARVER в колонке «Публикуется».")

    base_tags = cfg.feed.base_tags or {}
    if not str(base_tags.get("Category", "")).strip():
        issues.append("Заполните категорию Avito: feed.base_tags.Category.")
    if not (str(base_tags.get("GoodsType", "")).strip()
            or str(cfg.feed.product_type_default or "").strip()):
        issues.append("Заполните тип товара Avito: GoodsType или product_type_default.")

    pricing = cfg.pricing
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    price_confirmed = bool((raw.get("pricing", {}) or {}).get("price_confirmed", False))
    if (pricing.default_markup_pct <= 0 and pricing.min_margin_abs <= 0 and not pricing.rules
            and not price_confirmed):
        issues.append("Подтвердите розничную наценку: сейчас профиль публикует по закупочной цене.")

    photos = cfg.catalog.manual_photos or {}
    missing_photos = [
        row.representative_nc or row.series
        for row in selected_rows
        if not row.has_card and not photos.get(row.representative_nc)
    ]
    if missing_photos:
        sample = ", ".join(missing_photos[:5])
        rest = len(missing_photos) - 5
        suffix = f" и ещё {rest}" if rest > 0 else ""
        issues.append(
            "Загрузите фото из прайса для выбранных позиций: " + sample + suffix + ".")

    return issues
