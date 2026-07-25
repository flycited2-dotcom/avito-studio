from pathlib import Path

from avito_studio.catalog_service import CatalogRow
from avito_studio.content_card_import import (
    expected_filename,
    import_content_cards,
    match_content_cards,
)
from avito_studio.local_config import LocalConfig
from avito_studio.profiles import PROFILES


def _row(nc="UT-1", brand="Ballu", series="Водонагреватель Ballu BWH/S 80 Shell (сухой)"):
    return CatalogRow(
        key=f"price_xls|item|pricexls:{nc}", source="price_xls", brand=brand,
        series=series, sizes="—", stock_total=1, has_card=False, forced=False,
        selected=False, representative_nc=nc, price_range="10000 ₽",
    )


def _config(tmp_path: Path) -> LocalConfig:
    path = tmp_path / "appliances.yaml"
    path.write_text(
        "catalog:\n"
        "  manual_photos: {}\n"
        "  selected_series: [\"__none__\"]\n",
        encoding="utf-8",
    )
    return LocalConfig(path)


class FakeSsh:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def run(self, command):
        self.calls.append(command)
        return self.output


def test_expected_filename_repeats_content_factory_brand_model_contract():
    assert expected_filename(_row()) == "excel_ballu-bwh-s-80-shell.jpg"


def test_match_content_cards_is_exact_not_fuzzy():
    row = _row()
    matches = match_content_cards([row], {
        "excel_ballu-bwh-s-80-shell.jpg",
        "excel_ballu-bwh-s-50-shell.jpg",
    })
    assert matches == {
        "UT-1": "https://splithome.ru/static/cf-cards/excel_ballu-bwh-s-80-shell.jpg"
    }


def test_import_adds_photo_and_enables_only_exact_row(tmp_path):
    matched = _row()
    missed = _row("UT-2", "BQ", "Миксер BQ MX999")
    cfg = _config(tmp_path)
    ssh = FakeSsh("excel_ballu-bwh-s-80-shell.jpg\nexcel_bq-mx440.jpg\n")
    found, added, removed = import_content_cards(ssh, [matched, missed], cfg)

    assert (found, added, removed) == (1, 1, 0)
    reloaded = LocalConfig(cfg.path)
    assert reloaded.get_manual_photo("UT-1").endswith("excel_ballu-bwh-s-80-shell.jpg")
    assert reloaded.is_selected(matched.key)
    assert not reloaded.is_selected(missed.key)
    assert matched.has_card is True and matched.selected is True


def test_import_does_not_overwrite_owner_manual_photo(tmp_path):
    row = _row()
    cfg = _config(tmp_path)
    cfg.set_manual_photo("UT-1", "https://example.test/owner-photo.jpg")
    cfg.save()
    found, added, removed = import_content_cards(
        FakeSsh("excel_ballu-bwh-s-80-shell.jpg\n"), [row], cfg)
    assert (found, added, removed) == (1, 0, 0)
    assert LocalConfig(cfg.path).get_manual_photo("UT-1") == \
        "https://example.test/owner-photo.jpg"


def test_one_content_card_enables_only_one_colour_variant(tmp_path):
    first = _row("UT-1", "Blackton", "Пылесос Blackton VCA1401B (красный)")
    second = _row("UT-2", "Blackton", "Пылесос Blackton VCA1401B (синий)")
    cfg = _config(tmp_path)
    found, added, removed = import_content_cards(
        FakeSsh("excel_blackton-vca1401b.jpg\n"), [first, second], cfg)
    assert (found, added, removed) == (1, 1, 0)
    reloaded = LocalConfig(cfg.path)
    assert reloaded.get_manual_photo("UT-1")
    assert reloaded.get_manual_photo("UT-2") is None
    assert reloaded.is_selected(first.key)
    assert not reloaded.is_selected(second.key)


def test_removing_stale_auto_card_from_implicit_all_preserves_other_rows(tmp_path):
    stale = _row("UT-1")
    untouched = _row("UT-2", "BQ", "Миксер BQ MX999")
    stale.selected = True
    untouched.selected = True
    path = tmp_path / "appliances.yaml"
    path.write_text(
        "catalog:\n  manual_photos: {}\n  selected_series: []\n",
        encoding="utf-8",
    )
    cfg = LocalConfig(path)
    cfg.set_manual_photo(
        "UT-1", "https://splithome.ru/static/cf-cards/excel_old-card.jpg")

    found, added, removed = import_content_cards(
        FakeSsh(""), [stale, untouched], cfg)

    assert (found, added, removed) == (0, 0, 1)
    reloaded = LocalConfig(path)
    assert reloaded.is_selected(stale.key) is False
    assert reloaded.is_selected(untouched.key) is True


def test_appliances_profile_is_local_and_available_in_selector():
    profile = next(p for p in PROFILES if p.key == "appliances")
    assert profile.label == "Бытовая техника"
    assert profile.config_rel == "profiles/appliances.yaml"
    assert profile.local_catalog is True


def test_carver_profile_is_local_and_checked_before_publish():
    profile = next(p for p in PROFILES if p.key == "carver")
    assert profile.label == "Генераторы CARVER"
    assert profile.config_rel == "profiles/carver.yaml"
    assert profile.local_catalog is True
    assert profile.publish_enabled is True
