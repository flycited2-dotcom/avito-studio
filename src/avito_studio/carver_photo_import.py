"""Импорт встроенных фото из прайса CARVER в публичное хранилище студии."""
from __future__ import annotations

from pathlib import Path

from avito_bridge.config import load_config
from avito_bridge.ingest.carver_xlsx import extract_embedded_photos
from avito_studio.photo_upload import upload_manual_photo_bytes


def import_carver_photos(ssh, config_path: Path, rows, local_cfg) -> tuple[int, int, int]:
    """Точно сопоставляет фото по supplier SKU и грузит отсутствующие на VPS.

    Возвращает (найдено, загружено, сохранено владельцем). Позиции намеренно не
    выбираются для публикации: фото и готовность объявления — разные решения.
    """
    cfg = load_config(Path(config_path))
    price_path = (cfg.source_options or {}).get("path", "")
    if not price_path or not Path(price_path).exists():
        raise ValueError(f"Прайс CARVER не найден: {price_path!r}")
    embedded = extract_embedded_photos(price_path)
    by_article = {row.representative_nc: row for row in rows if row.representative_nc}
    articles = [article for article in by_article if article in embedded]
    found = len(articles)
    added = 0
    preserved = 0
    dirty = False
    try:
        for article in articles:
            row = by_article[article]
            if local_cfg.get_manual_photo(article):
                row.has_card = True
                preserved += 1
                continue
            url = upload_manual_photo_bytes(ssh, embedded[article], article)
            local_cfg.set_manual_photo(article, url)
            row.has_card = True
            added += 1
            dirty = True
    finally:
        # При сетевой ошибке сохраняем уже успешно загруженные URL: иначе файлы
        # останутся на VPS, а локальный профиль потеряет связь с ними.
        if dirty:
            local_cfg.save()
    return found, added, preserved
