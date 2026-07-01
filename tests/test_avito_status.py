from avito_studio.catalog_service import CatalogRow
from avito_studio.avito_status import match_statuses
from avito_bridge.feed.ad_id import make_ad_id

ROWS = [
    CatalogRow(key="breeze|funai|sensei 2.0", source="breeze", brand="Funai", series="Sensei 2.0",
              sizes="7 тыс. BTU", stock_total=2, has_card=True, forced=False, selected=True,
              representative_nc="НС-1"),
    CatalogRow(key="daichi|midea|изи", source="daichi", brand="Midea", series="Изи",
              sizes="12 тыс. BTU", stock_total=1, has_card=False, forced=False, selected=False,
              representative_nc="НС-2"),
]


def test_match_statuses_finds_matching_ad_id():
    known_ad_id = make_ad_id("breeze:НС-1", "simferopol")
    items = [{"ad_id": known_ad_id, "avito_status": "active",
             "url": "https://www.avito.ru/items/1"}]
    result = match_statuses(ROWS, items)
    assert result["breeze|funai|sensei 2.0"].avito_status == "active"
    assert result["breeze|funai|sensei 2.0"].url == "https://www.avito.ru/items/1"


def test_match_statuses_missing_ad_id_returns_none_status():
    result = match_statuses(ROWS, items=[])
    assert result["daichi|midea|изи"].avito_status is None
    assert result["daichi|midea|изи"].url is None
