"""Validated import of a CARVER supplier workbook into local runtime storage."""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from avito_bridge.ingest.carver_xlsx import extract_embedded_photos, parse_carver_xlsx

MAX_PRICE_AGE_DAYS = 90
MAX_FUTURE_SKEW_HOURS = 24
MAX_PRICE_FILE_BYTES = 50 * 1024 * 1024
MAX_REASONABLE_POSITIONS = 500
REQUIRED_ROW_FIELDS = frozenset(
    {"row", "article", "model", "name", "price", "kind"}
)


def resolve_carver_price_path(config_path: Path, configured_path: str | Path) -> Path:
    """Resolve a profile source path against its Bridge workspace, never CWD."""
    source = Path(configured_path).expanduser()
    if source.is_absolute():
        return source.resolve()
    bridge_root = Path(config_path).resolve().parent.parent
    return (bridge_root / source).resolve()


def validate_carver_price_metadata(
    source: Path, *, now: float | None = None
) -> Path:
    """Validate cheap file properties required both on import and publish."""
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.casefold() != ".xlsx":
        raise ValueError("Прайс CARVER должен быть файлом Excel с расширением .xlsx.")

    size = source.stat().st_size
    if size <= 0:
        raise ValueError("Выбран пустой XLSX-файл CARVER.")
    if size > MAX_PRICE_FILE_BYTES:
        raise ValueError(
            f"Прайс CARVER больше безопасного предела "
            f"{MAX_PRICE_FILE_BYTES // 1024 // 1024} МБ."
        )

    timestamp = time.time() if now is None else now
    modified_at = source.stat().st_mtime
    age_seconds = timestamp - modified_at
    if age_seconds > MAX_PRICE_AGE_DAYS * 24 * 60 * 60:
        raise ValueError(
            f"Прайс CARVER старше {MAX_PRICE_AGE_DAYS} дней. "
            "Выберите актуальный файл поставщика."
        )
    if age_seconds < -MAX_FUTURE_SKEW_HOURS * 60 * 60:
        raise ValueError(
            "Дата изменения прайса CARVER находится в будущем. "
            "Проверьте дату и время на устройстве."
        )
    return source


def validate_carver_price(source: Path, *, now: float | None = None) -> int:
    """Validate workbook shape, freshness and embedded product photos.

    The supplier catalog is allowed to grow or shrink: the old exact
    23-position check made a legitimate new price list impossible to import.
    The safety boundary is structural instead—at least one valid row, no
    duplicate articles, a bounded row count, a current file and one embedded
    photo for every product.
    """
    source = validate_carver_price_metadata(source, now=now)

    rows = parse_carver_xlsx(source)
    if not rows:
        raise ValueError(
            "В прайсе CARVER не найдено ни одной товарной позиции. "
            "Проверьте схему: модель — B, название — C, цена — F, данные — с 4-й строки."
        )
    if len(rows) > MAX_REASONABLE_POSITIONS:
        raise ValueError(
            f"В прайсе найдено {len(rows)} позиций — больше безопасного предела "
            f"{MAX_REASONABLE_POSITIONS}. Проверьте, что выбран именно прайс CARVER."
        )

    articles: set[str] = set()
    for index, row in enumerate(rows, start=1):
        missing_fields = REQUIRED_ROW_FIELDS.difference(row)
        if missing_fields:
            raise ValueError(
                f"Неверная схема позиции {index}: отсутствуют поля "
                + ", ".join(sorted(missing_fields))
            )
        article = str(row["article"]).strip()
        model = str(row["model"]).strip()
        name = str(row["name"]).strip()
        price = row["price"]
        if (not article or not model or not name or isinstance(price, bool)
                or not isinstance(price, (int, float)) or price <= 0):
            raise ValueError(f"Неверная схема или цена в позиции {index}.")
        if article in articles:
            raise ValueError(f"В прайсе повторяется артикул {article}.")
        articles.add(article)

    photos = extract_embedded_photos(source)
    missing = [str(row["article"]) for row in rows if str(row["article"]) not in photos]
    if missing:
        raise ValueError("Нет встроенных фото: " + ", ".join(missing[:5]))
    empty = [
        str(row["article"]) for row in rows
        if not isinstance(photos.get(str(row["article"])), bytes)
        or not photos[str(row["article"])]
    ]
    if empty:
        raise ValueError("Пустые встроенные фото: " + ", ".join(empty[:5]))
    return len(rows)


def import_carver_price(source: Path, bridge_root: Path) -> tuple[Path, int]:
    """Revalidate and atomically commit the workbook to runtime storage."""
    source = Path(source).resolve()
    count = validate_carver_price(source)

    target = Path(bridge_root) / "runtime" / "carver" / "current.xlsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    target = target.resolve()
    if source == target:
        return target, count

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".current.",
        suffix=".xlsx",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    try:
        with source.open("rb") as source_stream, os.fdopen(descriptor, "wb") as target_stream:
            descriptor_open = False
            shutil.copyfileobj(source_stream, target_stream)
            target_stream.flush()
            os.fsync(target_stream.fileno())
        staged_count = validate_carver_price(temporary)
        if staged_count != count:
            raise ValueError(
                "Прайс изменился во время копирования. Выберите файл повторно.")
        os.replace(temporary, target)
    finally:
        if descriptor_open:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return target, count
