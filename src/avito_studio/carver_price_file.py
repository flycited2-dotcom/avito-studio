"""Validated import of a CARVER supplier workbook into local runtime storage."""
from __future__ import annotations

from pathlib import Path
import shutil

from avito_bridge.ingest.carver_xlsx import extract_embedded_photos, parse_carver_xlsx


EXPECTED_POSITIONS = 23


def import_carver_price(source: Path, bridge_root: Path) -> tuple[Path, int]:
    """Validate and atomically copy the workbook without modifying the original."""
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)

    rows = parse_carver_xlsx(source)
    if len(rows) != EXPECTED_POSITIONS:
        raise ValueError(
            f"Ожидалось {EXPECTED_POSITIONS} товарных позиций, найдено {len(rows)}."
        )

    photos = extract_embedded_photos(source)
    missing = [str(row["article"]) for row in rows if str(row["article"]) not in photos]
    if missing:
        raise ValueError("Нет встроенных фото: " + ", ".join(missing[:5]))

    target = Path(bridge_root) / "runtime" / "carver" / "current.xlsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".xlsx.tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(target)
    return target.resolve(), len(rows)
