import pytest
from avito_bridge.feed.ad_id import make_ad_id

from avito_studio.avito_status import (
    build_client,
    credential_names,
    fetch_statuses,
    match_statuses,
)
from avito_studio.catalog_service import CatalogMember, CatalogRow

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


def test_match_statuses_prefers_exact_exported_supplier_sku():
    row = CatalogRow(
        key="carver|generator|ppg",
        source="carver_xlsx",
        brand="CARVER",
        series="PPG",
        sizes="—",
        stock_total=1,
        has_card=True,
        forced=False,
        selected=True,
        representative_nc="PPG-1900IS",
        members=(CatalogMember(
            "PPG-1900IS", 30000, 20000, True, False,
            "carver:PPG-1900IS", "supplier"),),
    )
    exact_ad_id = make_ad_id("carver:PPG-1900IS", "simferopol")
    items = [{"ad_id": exact_ad_id, "avito_status": "active", "url": "https://x/carver"}]

    result = match_statuses([row], items)

    assert result[row.key].avito_status == "active"
    assert result[row.key].url == "https://x/carver"


def test_build_client_uses_wreath_account_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("AVITO_CLIENT_ID_WREATHS", raising=False)
    monkeypatch.delenv("AVITO_CLIENT_SECRET_WREATHS", raising=False)
    (tmp_path / ".env").write_text(
        "AVITO_CLIENT_ID=main-id\n"
        "AVITO_CLIENT_SECRET=main-secret\n"
        "AVITO_CLIENT_ID_WREATHS=wreath-id\n"
        "AVITO_CLIENT_SECRET_WREATHS=wreath-secret\n",
        encoding="utf-8",
    )
    client = build_client(tmp_path, "wreaths")
    try:
        assert client.client_id == "wreath-id"
        assert client.client_secret == "wreath-secret"
    finally:
        client.close()


@pytest.mark.parametrize(
    ("profile_key", "suffix"),
    [
        ("conditioners", ""),
        ("wreaths", "_WREATHS"),
        ("carver", "_CARVER"),
        ("appliances", "_APPLIANCES"),
    ],
)
def test_build_client_uses_process_env_without_dotenv(
    tmp_path, monkeypatch, profile_key, suffix
):
    client_id_name = f"AVITO_CLIENT_ID{suffix}"
    secret_name = f"AVITO_CLIENT_SECRET{suffix}"
    monkeypatch.setenv(client_id_name, f"{profile_key}-id")
    monkeypatch.setenv(secret_name, f"{profile_key}-secret")

    client = build_client(tmp_path, profile_key)
    try:
        assert client.client_id == f"{profile_key}-id"
        assert client.client_secret == f"{profile_key}-secret"
    finally:
        client.close()


def test_unknown_status_profile_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="Неизвестный профиль"):
        build_client(tmp_path, "wrong-profile")


def test_profile_credentials_never_fall_back_to_main_account(tmp_path, monkeypatch):
    monkeypatch.setenv("AVITO_CLIENT_ID", "main-id")
    monkeypatch.setenv("AVITO_CLIENT_SECRET", "main-secret")
    monkeypatch.delenv("AVITO_CLIENT_ID_CARVER", raising=False)
    monkeypatch.delenv("AVITO_CLIENT_SECRET_CARVER", raising=False)

    with pytest.raises(ValueError, match="AVITO_CLIENT_ID_CARVER"):
        build_client(tmp_path, "carver")


def test_credential_names_match_bridge_profile_routing():
    assert credential_names("conditioners") == (
        "AVITO_CLIENT_ID", "AVITO_CLIENT_SECRET")
    assert credential_names("wreaths") == (
        "AVITO_CLIENT_ID_WREATHS", "AVITO_CLIENT_SECRET_WREATHS")
    assert credential_names("carver") == (
        "AVITO_CLIENT_ID_CARVER", "AVITO_CLIENT_SECRET_CARVER")
    assert credential_names("appliances") == (
        "AVITO_CLIENT_ID_APPLIANCES", "AVITO_CLIENT_SECRET_APPLIANCES")


def test_fetch_statuses_always_closes_client(monkeypatch, tmp_path):
    class FakeClient:
        closed = False

        def last_successful_items(self):
            return []

        def close(self):
            self.closed = True

    client = FakeClient()
    monkeypatch.setattr(
        "avito_studio.avito_status.build_client",
        lambda bridge_root, profile_key: client,
    )

    assert fetch_statuses(tmp_path, ROWS, "conditioners")
    assert client.closed is True


def test_match_statuses_uses_exported_ad_id_revision():
    row = CatalogRow(
        key="ritualb2b|item|ritualb2b:venok-dafna",
        source="ritualb2b",
        brand="",
        series="Дафна",
        sizes="—",
        stock_total=1,
        has_card=True,
        forced=False,
        selected=True,
        representative_nc="venok-dafna",
        members=(
            CatalogMember(
                "venok-dafna",
                1000,
                1000,
                True,
                False,
                "ritualb2b:venok-dafna",
                "supplier",
                2,
            ),
        ),
    )
    revised = make_ad_id("ritualb2b:venok-dafna", "simferopol", revision=2)

    result = match_statuses(
        [row],
        [{"ad_id": revised, "avito_status": "rejected", "url": None}],
    )

    assert result[row.key].avito_status == "rejected"
