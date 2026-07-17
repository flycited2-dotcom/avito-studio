from pathlib import Path

import pytest

from avito_studio import carver_price_file as price_file


def test_valid_price_is_copied_only_after_validation(tmp_path, monkeypatch):
    source = tmp_path / "price.xlsx"
    source.write_bytes(b"xlsx")
    monkeypatch.setattr(
        price_file,
        "parse_carver_xlsx",
        lambda path: [{"article": str(i)} for i in range(23)],
    )
    monkeypatch.setattr(
        price_file,
        "extract_embedded_photos",
        lambda path: {str(i): b"photo" for i in range(23)},
    )

    target, count = price_file.import_carver_price(source, tmp_path / "bridge")

    assert target == (tmp_path / "bridge" / "runtime" / "carver" / "current.xlsx").resolve()
    assert target.read_bytes() == b"xlsx"
    assert count == 23


def test_invalid_price_does_not_replace_current(tmp_path, monkeypatch):
    current = tmp_path / "bridge" / "runtime" / "carver" / "current.xlsx"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"last-good")
    source = tmp_path / "bad.xlsx"
    source.write_bytes(b"bad")
    monkeypatch.setattr(price_file, "parse_carver_xlsx", lambda path: [])

    with pytest.raises(ValueError, match="товарных позиций"):
        price_file.import_carver_price(source, tmp_path / "bridge")

    assert current.read_bytes() == b"last-good"


def test_price_without_matching_embedded_photo_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "price.xlsx"
    source.write_bytes(b"xlsx")
    rows = [{"article": str(i)} for i in range(23)]
    monkeypatch.setattr(price_file, "parse_carver_xlsx", lambda path: rows)
    monkeypatch.setattr(
        price_file,
        "extract_embedded_photos",
        lambda path: {str(i): b"photo" for i in range(22)},
    )

    with pytest.raises(ValueError, match="Нет встроенных фото: 22"):
        price_file.import_carver_price(source, tmp_path / "bridge")


def test_missing_source_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        price_file.import_carver_price(Path(tmp_path / "missing.xlsx"), tmp_path / "bridge")
