from pathlib import Path

import avito_studio.carver_photo_import as importer
from avito_studio.catalog_service import CatalogRow
from avito_studio.local_config import LocalConfig


def _row(article="PPG-1900IS"):
    return CatalogRow(
        key=f"carver_xlsx|item|carver:{article}", source="carver_xlsx", brand="CARVER",
        series=f"Генератор CARVER {article}", sizes="—", stock_total=1,
        has_card=False, forced=False, selected=False, representative_nc=article,
        price_range="22786 ₽",
    )


def _config(tmp_path: Path) -> LocalConfig:
    price = tmp_path / "carver.xlsx"
    price.write_bytes(b"not-read-directly")
    path = tmp_path / "carver.yaml"
    path.write_text(
        "profile:\n"
        "  name: carver\n"
        "  source: carver_xlsx\n"
        f"  source_options: {{path: '{price.as_posix()}'}}\n"
        "catalog:\n"
        "  manual_photos: {}\n"
        "  selected_series: [\"__none__\"]\n",
        encoding="utf-8",
    )
    return LocalConfig(path)


class FakeSsh:
    pass


def test_import_uploads_exact_embedded_photo_but_does_not_select(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    row = _row()
    monkeypatch.setattr(importer, "extract_embedded_photos",
                        lambda path: {"PPG-1900IS": b"png"})
    uploads = []

    def upload(ssh, data, article):
        uploads.append((data, article))
        return f"https://example.test/{article}.jpg"

    monkeypatch.setattr(importer, "upload_manual_photo_bytes", upload)
    result = importer.import_carver_photos(FakeSsh(), cfg.path, [row], cfg)
    assert result == (1, 1, 0)
    assert uploads == [(b"png", "PPG-1900IS")]
    reloaded = LocalConfig(cfg.path)
    assert reloaded.get_manual_photo("PPG-1900IS").endswith("PPG-1900IS.jpg")
    assert not reloaded.is_selected(row.key)
    assert row.has_card is True and row.selected is False


def test_import_preserves_owner_photo(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    cfg.set_manual_photo("PPG-1900IS", "https://example.test/owner.jpg")
    cfg.save()
    row = _row()
    monkeypatch.setattr(importer, "extract_embedded_photos",
                        lambda path: {"PPG-1900IS": b"png"})
    monkeypatch.setattr(
        importer, "upload_manual_photo_bytes",
        lambda *a: (_ for _ in ()).throw(AssertionError("must not upload")))
    assert importer.import_carver_photos(FakeSsh(), cfg.path, [row], cfg) == (1, 0, 1)
    assert LocalConfig(cfg.path).get_manual_photo("PPG-1900IS") == \
        "https://example.test/owner.jpg"
    assert row.has_card is True


def test_relative_price_path_is_resolved_from_bridge_root_not_cwd(
    tmp_path, monkeypatch
):
    bridge_root = tmp_path / "bridge"
    price = bridge_root / "runtime" / "carver" / "current.xlsx"
    price.parent.mkdir(parents=True)
    price.write_bytes(b"not-read-directly")
    config_path = bridge_root / "profiles" / "carver.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        "profile:\n"
        "  name: carver\n"
        "  source: carver_xlsx\n"
        "  source_options: {path: runtime/carver/current.xlsx}\n"
        "catalog:\n"
        "  manual_photos: {}\n"
        "  selected_series: [\"__none__\"]\n",
        encoding="utf-8",
    )
    local_cfg = LocalConfig(config_path)
    observed = []
    monkeypatch.setattr(
        importer,
        "extract_embedded_photos",
        lambda path: observed.append(Path(path)) or {},
    )
    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    assert importer.import_carver_photos(
        FakeSsh(), config_path, [_row()], local_cfg
    ) == (0, 0, 0)
    assert observed == [price.resolve()]
