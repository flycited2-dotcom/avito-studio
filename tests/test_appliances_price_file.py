from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from avito_studio import appliances_price_file as price_file
from avito_studio.local_config import LocalConfig


def _supplier_fixture(tmp_path: Path) -> Path:
    source = tmp_path / "supplier.xls"
    source.write_bytes(b"synthetic supplier workbook")
    return source


SYNTHETIC_ROWS = [
    {
        "article": "K-001",
        "group": "Электрочайники",
        "brand": "TEST",
        "name": "Чайник TEST K1",
        "price": 1000.0,
        "stock_label": "Под заказ",
    },
    {
        "article": "F-001",
        "group": "Холодильники",
        "brand": "TEST",
        "name": "Холодильник TEST F1",
        "price": 20000.0,
        "stock_label": "",
    },
]


@pytest.fixture
def valid_supplier(tmp_path, monkeypatch):
    source = _supplier_fixture(tmp_path)
    monkeypatch.setattr(price_file, "_validate_workbook_shape", lambda _path: None)
    monkeypatch.setattr(
        price_file,
        "parse_price_xls",
        lambda _path: deepcopy(SYNTHETIC_ROWS),
    )
    return source


def _config(tmp_path: Path, source_path: str = "old.xls") -> LocalConfig:
    path = tmp_path / "bridge" / "profiles" / "appliances.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "profile:\n"
        "  name: appliances\n"
        "  source_options:\n"
        f'    path: "{source_path}"\n'
        "catalog:\n"
        "  selected_series: []\n",
        encoding="utf-8",
    )
    return LocalConfig(path)


def test_validate_synthetic_supplier_contract(valid_supplier):
    source = valid_supplier

    assert price_file.validate_appliances_price(
        source, now=source.stat().st_mtime
    ) == len(SYNTHETIC_ROWS)


def test_validate_workbook_shape_accepts_expected_headers(tmp_path, monkeypatch):
    source = _supplier_fixture(tmp_path)
    cells = {
        (0, 0): "Код",
        (0, 1): "Группа",
        (0, 2): "Производитель",
        (0, 3): "Номенклатура",
        (2, 4): "Цена",
    }

    class FakeSheet:
        nrows = 4
        ncols = 5

        @staticmethod
        def cell_value(row, column):
            return cells.get((row, column), "")

    class FakeBook:
        nsheets = 1
        released = False

        @staticmethod
        def sheet_by_index(index):
            assert index == 0
            return FakeSheet()

        def release_resources(self):
            self.released = True

    book = FakeBook()
    monkeypatch.setattr(
        price_file.xlrd, "open_workbook", lambda *_args, **_kwargs: book
    )

    price_file._validate_workbook_shape(source)

    assert book.released is True


def test_validate_rejects_wrong_extension_before_parsing(tmp_path):
    source = tmp_path / "supplier.xlsx"
    source.write_bytes(b"not-xls")

    with pytest.raises(ValueError, match=r"\.xls"):
        price_file.validate_appliances_price(source)


def test_validate_rejects_corrupt_xls_with_clear_structure_error(tmp_path):
    source = tmp_path / "supplier.xls"
    source.write_bytes(b"this is not an Excel workbook")

    with pytest.raises(ValueError, match="повреждён|открыть"):
        price_file.validate_appliances_price(source)


def test_validate_rejects_stale_and_future_files(valid_supplier):
    source = valid_supplier
    modified = source.stat().st_mtime

    with pytest.raises(ValueError, match="старше"):
        price_file.validate_appliances_price(
            source,
            now=modified + (price_file.MAX_PRICE_AGE_DAYS + 1) * 24 * 60 * 60,
        )
    with pytest.raises(ValueError, match="будущем"):
        price_file.validate_appliances_price(
            source,
            now=modified - (price_file.MAX_FUTURE_SKEW_HOURS + 1) * 60 * 60,
        )


def test_validate_rejects_empty_catalog(valid_supplier, monkeypatch):
    source = valid_supplier
    monkeypatch.setattr(price_file, "parse_price_xls", lambda _path: [])

    with pytest.raises(ValueError, match="ни одной непустой"):
        price_file.validate_appliances_price(source)


def test_validate_rejects_unreasonable_row_count(valid_supplier, monkeypatch):
    source = valid_supplier
    row = {
        "article": "A",
        "group": "G",
        "brand": "",
        "name": "N",
        "price": 1.0,
        "stock_label": "",
    }
    monkeypatch.setattr(
        price_file,
        "parse_price_xls",
        lambda _path: [row] * (price_file.MAX_REASONABLE_POSITIONS + 1),
    )

    with pytest.raises(ValueError, match="безопасного предела"):
        price_file.validate_appliances_price(source)


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            {
                "article": "",
                "group": "G",
                "brand": "",
                "name": "N",
                "price": 1.0,
                "stock_label": "",
            },
            "пустой код",
        ),
        (
            {
                "article": "A",
                "group": "G",
                "brand": "",
                "name": "N",
                "price": 0,
                "stock_label": "",
            },
            "неверная цена",
        ),
        (
            {
                "article": "A",
                "group": "G",
                "name": "N",
                "price": 1.0,
                "stock_label": "",
            },
            "отсутствуют поля",
        ),
    ],
)
def test_validate_rejects_malformed_rows(
    valid_supplier, monkeypatch, row, message
):
    source = valid_supplier
    monkeypatch.setattr(price_file, "parse_price_xls", lambda _path: [row])

    with pytest.raises(ValueError, match=message):
        price_file.validate_appliances_price(source)


def test_import_atomically_installs_portable_runtime_file(
    tmp_path, valid_supplier
):
    source = valid_supplier
    bridge_root = tmp_path / "bridge"
    local_cfg = _config(tmp_path)

    target, count = price_file.import_appliances_price(
        source, bridge_root, local_cfg
    )

    assert count == len(SYNTHETIC_ROWS)
    assert target == bridge_root.resolve() / "runtime" / "appliances" / "current.xls"
    assert target.read_bytes() == source.read_bytes()
    reloaded = LocalConfig(local_cfg.path)
    assert reloaded.get_source_path() == "runtime/appliances/current.xls"


def test_import_restores_previous_runtime_file_when_yaml_save_fails(
    tmp_path, valid_supplier, monkeypatch
):
    source = valid_supplier
    bridge_root = tmp_path / "bridge"
    target = bridge_root / "runtime" / "appliances" / "current.xls"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous-price")
    local_cfg = _config(tmp_path, "runtime/appliances/previous.xls")
    original_yaml = local_cfg.path.read_text(encoding="utf-8")
    monkeypatch.setattr(
        local_cfg,
        "save",
        lambda: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        price_file.import_appliances_price(source, bridge_root, local_cfg)

    assert target.read_bytes() == b"previous-price"
    assert local_cfg.path.read_text(encoding="utf-8") == original_yaml
    assert local_cfg.get_source_path() == "runtime/appliances/previous.xls"
    assert not list(target.parent.glob(".current.*"))


def test_import_rejects_source_changed_while_copying(
    tmp_path, valid_supplier, monkeypatch
):
    source = valid_supplier
    bridge_root = tmp_path / "bridge"
    local_cfg = _config(tmp_path)
    real_sha256 = price_file._sha256
    calls = 0

    def changing_digest(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            return "changed"
        return real_sha256(path)

    monkeypatch.setattr(price_file, "_sha256", changing_digest)

    with pytest.raises(ValueError, match="изменился во время копирования"):
        price_file.import_appliances_price(source, bridge_root, local_cfg)

    assert not (bridge_root / "runtime" / "appliances" / "current.xls").exists()
    assert local_cfg.get_source_path() == "old.xls"
