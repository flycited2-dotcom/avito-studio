"""Импорт уже готовых карточек МБТ/КБТ из серверной библиотеки «Контент-завода».

Контент-завод именует Excel-карточки как ``excel_<brand>-<model>.jpg``. Здесь
повторён его маленький детерминированный алгоритм имени: только точное совпадение,
без fuzzy-поиска и догадок. Совпавшая карточка записывается как manual_photos по
артикулу прайса и позиция включается в whitelist профиля.
"""
from __future__ import annotations
import re
from urllib.parse import quote

from avito_studio.catalog_service import CatalogRow
from avito_studio.local_config import LocalConfig

REMOTE_CARDS_DIR = "/opt/oasis/staticfiles/cf-cards"
PUBLIC_CARDS_BASE = "https://splithome.ru/static/cf-cards"
LIST_CARDS_CMD = (
    f"find {REMOTE_CARDS_DIR} -maxdepth 1 -type f "
    r"\( -name '*.jpg' -o -name '*.jpeg' -o -name '*.png' \) -printf '%f\n'"
)
_PAREN_RE = re.compile(r"\([^)]*\)")


def slug(value: str) -> str:
    """Тот же slug, что content_factory.orchestrator.card_submit.slug."""
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:60]


def extract_model(name: str, brand: str) -> str:
    """Модель после бренда, без характеристик в скобках — контракт Контент-завода."""
    clean = _PAREN_RE.sub("", name or "").strip()
    match = re.search(re.escape(brand or ""), clean, re.IGNORECASE) if brand else None
    if match:
        tail = clean[match.end():].strip(" -–—·")
        if tail:
            return re.sub(r"\s+", " ", tail)
    return re.sub(r"\s+", " ", clean)


def expected_filename(row: CatalogRow) -> str:
    model = extract_model(row.series, row.brand)
    return f"excel_{slug(row.brand)}-{slug(model)}.jpg"


def match_content_cards(rows: list[CatalogRow], filenames: set[str]) -> dict[str, str]:
    """{артикул: публичный URL}; одно точное имя карточки = одно объявление.

    В прайсе встречаются цветовые варианты одной модели, а Контент-завод хранит для
    них одну карточку. Повторять одинаковое фото в нескольких объявлениях нельзя:
    Avito расценит их как дубли. Берём первую строку в детерминированном порядке прайса.
    """
    by_lower = {name.lower(): name for name in filenames}
    matches: dict[str, str] = {}
    used_files: set[str] = set()
    for row in rows:
        if not row.representative_nc:
            continue
        actual = by_lower.get(expected_filename(row).lower())
        if actual and actual.lower() not in used_files:
            matches[row.representative_nc] = f"{PUBLIC_CARDS_BASE}/{quote(actual)}"
            used_files.add(actual.lower())
    return matches


def import_content_cards(ssh, rows: list[CatalogRow],
                         local_cfg: LocalConfig) -> tuple[int, int, int]:
    """Синхронизировать точные совпадения. Возвращает (найдено, добавлено, убрано).

    Ручное фото владельца не перезаписываем. Любая позиция, у которой после импорта
    есть фото, включается в whitelist — безопасный профиль стартует с ``__none__``.
    """
    filenames = {line.strip() for line in ssh.run(LIST_CARDS_CMD).splitlines() if line.strip()}
    matches = match_content_cards(rows, filenames)
    added = 0
    removed = 0
    rows_by_nc = {row.representative_nc: row for row in rows}
    # Удаляем только старые АВТОИМПОРТИРОВАННЫЕ ссылки, которые больше не входят в
    # точный уникальный набор. Фото, выбранные владельцем вручную, не трогаем.
    for row in rows:
        current = local_cfg.get_manual_photo(row.representative_nc) or ""
        if row.representative_nc not in matches and current.startswith(PUBLIC_CARDS_BASE + "/"):
            local_cfg.remove_manual_photo(row.representative_nc)
            local_cfg.set_selected(row.key, False)
            row.has_card = False
            row.selected = False
            removed += 1
    for nc_code, url in matches.items():
        row = rows_by_nc[nc_code]
        if not local_cfg.get_manual_photo(nc_code):
            local_cfg.set_manual_photo(nc_code, url)
            added += 1
        local_cfg.set_selected(row.key, True)
        row.has_card = True
        row.selected = True
    local_cfg.save()
    return len(matches), added, removed
