import os
import time
from pathlib import Path

import pytest

from avito_studio import carver_price_file as price_file


def _rows(count):
    return [
        {
            "row": index + 4,
            "article": f"PPG-{index}",
            "model": f"PPG-{index}",
            "name": f"Генератор {index}",
            "price": 10_000 + index,
            "kind": "generator",
        }
        for index in range(count)
    ]


def _mock_valid_workbook(monkeypatch, count):
    rows = _rows(count)
    monkeypatch.setattr(price_file, "parse_carver_xlsx", lambda path: rows)
    monkeypatch.setattr(
        price_file,
        "extract_embedded_photos",
        lambda path: {row["article"]: b"photo" for row in rows},
    )
    return rows


def test_valid_price_with_changed_product_count_is_copied_after_validation(
        tmp_path, monkeypatch):
    source = tmp_path / "price.xlsx"
    source.write_bytes(b"xlsx")
    _mock_valid_workbook(monkeypatch, 24)

    target, count = price_file.import_carver_price(source, tmp_path / "bridge")

    assert target == (tmp_path / "bridge" / "runtime" / "carver" / "current.xlsx").resolve()
    assert target.read_bytes() == b"xlsx"
    assert count == 24


def test_invalid_price_does_not_replace_current(tmp_path, monkeypatch):
    current = tmp_path / "bridge" / "runtime" / "carver" / "current.xlsx"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"last-good")
    source = tmp_path / "bad.xlsx"
    source.write_bytes(b"bad")
    monkeypatch.setattr(price_file, "parse_carver_xlsx", lambda path: [])

    with pytest.raises(ValueError, match="ни одной товарной позиции"):
        price_file.import_carver_price(source, tmp_path / "bridge")

    assert current.read_bytes() == b"last-good"


def test_price_without_matching_embedded_photo_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "price.xlsx"
    source.write_bytes(b"xlsx")
    rows = _rows(23)
    monkeypatch.setattr(price_file, "parse_carver_xlsx", lambda path: rows)
    monkeypatch.setattr(
        price_file,
        "extract_embedded_photos",
        lambda path: {row["article"]: b"photo" for row in rows[:-1]},
    )

    with pytest.raises(ValueError, match=f"Нет встроенных фото: {rows[-1]['article']}"):
        price_file.import_carver_price(source, tmp_path / "bridge")


def test_missing_source_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        price_file.import_carver_price(Path(tmp_path / "missing.xlsx"), tmp_path / "bridge")


def test_stale_price_is_rejected_before_parsing(tmp_path, monkeypatch):
    source = tmp_path / "stale.xlsx"
    source.write_bytes(b"xlsx")
    old = time.time() - (price_file.MAX_PRICE_AGE_DAYS + 1) * 24 * 60 * 60
    os.utime(source, (old, old))
    parsed = {"called": False}
    monkeypatch.setattr(
        price_file,
        "parse_carver_xlsx",
        lambda path: parsed.update(called=True) or _rows(1),
    )

    with pytest.raises(ValueError, match="старше"):
        price_file.validate_carver_price(source)

    assert parsed["called"] is False


def test_duplicate_articles_are_rejected(tmp_path, monkeypatch):
    source = tmp_path / "duplicate.xlsx"
    source.write_bytes(b"xlsx")
    rows = _rows(2)
    rows[1]["article"] = rows[0]["article"]
    monkeypatch.setattr(price_file, "parse_carver_xlsx", lambda path: rows)

    with pytest.raises(ValueError, match="повторяется артикул"):
        price_file.validate_carver_price(source)


def test_missing_row_schema_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "wrong-schema.xlsx"
    source.write_bytes(b"xlsx")
    row = _rows(1)[0]
    del row["name"]
    monkeypatch.setattr(price_file, "parse_carver_xlsx", lambda path: [row])

    with pytest.raises(ValueError, match="отсутствуют поля name"):
        price_file.validate_carver_price(source)


def test_unreasonable_position_count_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "not-a-price.xlsx"
    source.write_bytes(b"xlsx")
    monkeypatch.setattr(
        price_file,
        "parse_carver_xlsx",
        lambda path: _rows(price_file.MAX_REASONABLE_POSITIONS + 1),
    )

    with pytest.raises(ValueError, match="безопасного предела"):
        price_file.validate_carver_price(source)


def test_oversized_price_is_rejected_before_workbook_parsing(tmp_path, monkeypatch):
    source = tmp_path / "oversized.xlsx"
    source.write_bytes(b"too-large")
    monkeypatch.setattr(price_file, "MAX_PRICE_FILE_BYTES", 4)

    with pytest.raises(ValueError, match="безопасного предела"):
        price_file.validate_carver_price(source)


def test_failed_atomic_replace_preserves_current_price(tmp_path, monkeypatch):
    bridge_root = tmp_path / "bridge"
    current = bridge_root / "runtime" / "carver" / "current.xlsx"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"last-good")
    source = tmp_path / "new.xlsx"
    source.write_bytes(b"new-price")
    _mock_valid_workbook(monkeypatch, 25)
    monkeypatch.setattr(
        price_file.os,
        "replace",
        lambda *args: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        price_file.import_carver_price(source, bridge_root)

    assert current.read_bytes() == b"last-good"
    assert list(current.parent.glob(".current.*.xlsx")) == []
