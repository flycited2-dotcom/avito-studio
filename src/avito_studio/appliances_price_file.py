"""Safe, portable import of the appliances supplier ``.xls`` price list."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from copy import deepcopy
from pathlib import Path

import xlrd

from avito_bridge.ingest.price_xls import parse_price_xls
from avito_studio.atomic_io import atomic_write_text
from avito_studio.local_config import LocalConfig

MAX_PRICE_AGE_DAYS = 30
MAX_FUTURE_SKEW_HOURS = 24
MAX_PRICE_FILE_BYTES = 50 * 1024 * 1024
MAX_REASONABLE_POSITIONS = 10_000
REQUIRED_ROW_FIELDS = frozenset(
    {"article", "group", "brand", "name", "price", "stock_label"}
)


def _normalized_cell(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _validate_workbook_shape(source: Path) -> None:
    """Reject an arbitrary spreadsheet before the generic row parser sees it."""
    try:
        book = xlrd.open_workbook(str(source), on_demand=True)
    except Exception as exc:
        raise ValueError(
            "Файл не удалось открыть как старый Excel-прайс (.xls). "
            "Возможно, он повреждён или имеет другое расширение."
        ) from exc
    try:
        if book.nsheets < 1:
            raise ValueError("В XLS-прайсе нет ни одного листа.")
        sheet = book.sheet_by_index(0)
        if sheet.nrows < 4 or sheet.ncols < 5:
            raise ValueError(
                "Неверная структура XLS-прайса: ожидаются две строки заголовка "
                "и колонки «Код», «Группа», «Производитель», «Номенклатура», «Цена»."
            )
        headers = (
            (_normalized_cell(sheet.cell_value(0, 0)), "код"),
            (_normalized_cell(sheet.cell_value(0, 1)), "групп"),
            (_normalized_cell(sheet.cell_value(0, 2)), "производ"),
            (_normalized_cell(sheet.cell_value(0, 3)), "номенклатур"),
            (_normalized_cell(sheet.cell_value(2, 4)), "цен"),
        )
        if any(marker not in value for value, marker in headers):
            raise ValueError(
                "Неверная структура XLS-прайса: заголовки первых пяти колонок "
                "не соответствуют прайсу бытовой техники."
            )
    finally:
        book.release_resources()


def validate_appliances_price(source: Path, *, now: float | None = None) -> int:
    """Validate file type, freshness, workbook schema and every parsed row."""
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"Файл прайса не найден: {source}")
    if source.suffix.casefold() != ".xls":
        raise ValueError("Прайс бытовой техники должен иметь расширение .xls.")

    stat = source.stat()
    if stat.st_size <= 0:
        raise ValueError("Выбран пустой XLS-файл.")
    if stat.st_size > MAX_PRICE_FILE_BYTES:
        raise ValueError(
            f"XLS-файл больше безопасного предела {MAX_PRICE_FILE_BYTES // 1024 // 1024} МБ."
        )

    timestamp = time.time() if now is None else now
    age_seconds = timestamp - stat.st_mtime
    if age_seconds > MAX_PRICE_AGE_DAYS * 24 * 60 * 60:
        raise ValueError(
            f"Прайс старше {MAX_PRICE_AGE_DAYS} дней. "
            "Выберите актуальный файл поставщика."
        )
    if age_seconds < -MAX_FUTURE_SKEW_HOURS * 60 * 60:
        raise ValueError(
            "Дата изменения прайса находится в будущем. "
            "Проверьте дату и время на устройстве."
        )

    _validate_workbook_shape(source)
    try:
        rows = parse_price_xls(source)
    except Exception as exc:
        raise ValueError(f"Не удалось прочитать товарные строки XLS-прайса: {exc}") from exc
    if not rows:
        raise ValueError("В XLS-прайсе не найдено ни одной непустой товарной строки.")
    if len(rows) > MAX_REASONABLE_POSITIONS:
        raise ValueError(
            f"В прайсе найдено {len(rows)} позиций — больше безопасного предела "
            f"{MAX_REASONABLE_POSITIONS}."
        )

    articles: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Неверная структура товарной строки {index}.")
        missing = REQUIRED_ROW_FIELDS.difference(row)
        if missing:
            raise ValueError(
                f"В товарной строке {index} отсутствуют поля: "
                + ", ".join(sorted(missing))
            )
        article = str(row["article"]).strip()
        group = str(row["group"]).strip()
        name = str(row["name"]).strip()
        price = row["price"]
        if not article or not group or not name:
            raise ValueError(
                f"В товарной строке {index} пустой код, группа или наименование."
            )
        if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
            raise ValueError(f"В товарной строке {index} указана неверная цена.")
        if article in articles:
            raise ValueError(f"В прайсе повторяется код товара {article}.")
        articles.add(article)
    return len(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _restore_config(local_cfg: LocalConfig, old_data, old_text: str) -> None:
    local_cfg.data = old_data
    try:
        if local_cfg.path.read_text(encoding="utf-8") != old_text:
            atomic_write_text(local_cfg.path, old_text)
    except OSError:
        # Preserve the original import exception. A subsequent LocalConfig load
        # will still surface a filesystem problem explicitly.
        pass


def import_appliances_price(
    source: Path,
    bridge_root: Path,
    local_cfg: LocalConfig,
) -> tuple[Path, int]:
    """Validate, atomically install and point the profile at a portable path.

    The target and profile YAML are treated as one transaction: if saving the
    YAML fails, the previous runtime file is restored (or the new one removed).
    """
    source = Path(source).resolve()
    count = validate_appliances_price(source)
    source_digest = _sha256(source)

    root = Path(bridge_root).resolve()
    target = root / "runtime" / "appliances" / "current.xls"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.parent.resolve().is_relative_to(root):
        raise ValueError("Каталог runtime/appliances выходит за пределы bridge_root.")
    if target.is_symlink():
        raise ValueError("Файл runtime/appliances/current.xls не должен быть ссылкой.")

    old_data = deepcopy(local_cfg.data)
    old_text = local_cfg.path.read_text(encoding="utf-8")
    if source == target.resolve(strict=False):
        try:
            local_cfg.set_source_path(target, relative_to=root)
            local_cfg.save()
        except Exception:
            _restore_config(local_cfg, old_data, old_text)
            raise
        return target, count

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".current.",
        suffix=".xls",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    backup: Path | None = None
    try:
        with source.open("rb") as source_stream, os.fdopen(descriptor, "wb") as target_stream:
            descriptor_open = False
            shutil.copyfileobj(source_stream, target_stream)
            target_stream.flush()
            os.fsync(target_stream.fileno())
        if _sha256(source) != source_digest or _sha256(temporary) != source_digest:
            raise ValueError(
                "Прайс изменился во время копирования. Выберите файл повторно."
            )
        staged_count = validate_appliances_price(temporary)
        if staged_count != count:
            raise ValueError(
                "Количество строк изменилось во время копирования. "
                "Выберите файл повторно."
            )

        if target.exists():
            backup = target.with_name(f".current.backup.{os.getpid()}.xls")
            if backup.exists():
                raise FileExistsError(
                    f"Не удалось создать резервную копию: уже существует {backup}"
                )
            os.replace(target, backup)
        try:
            os.replace(temporary, target)
        except Exception:
            if backup is not None:
                os.replace(backup, target)
                backup = None
            raise

        try:
            local_cfg.set_source_path(target, relative_to=root)
            local_cfg.save()
        except Exception:
            _restore_config(local_cfg, old_data, old_text)
            if backup is not None:
                os.replace(backup, target)
                backup = None
            else:
                target.unlink(missing_ok=True)
            raise
        if backup is not None:
            backup.unlink(missing_ok=True)
            backup = None
        return target, count
    finally:
        if descriptor_open:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        if backup is not None:
            # Never delete the only copy of the previous price on an error.
            # If restoration cannot happen here, leave the clearly named
            # backup beside the target for manual recovery.
            if not target.exists():
                os.replace(backup, target)
