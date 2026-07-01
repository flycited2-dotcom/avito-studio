"""Сопоставление наших серий с реальным статусом объявления на Avito.

Ключ сопоставления: avito_bridge.feed.ad_id.make_ad_id(supplier_sku, city_id) — тот же хэш,
что Avito возвращает как ad_id в отчётах автозагрузки (подтверждено живым запросом). У нас всегда
ОДИН город (см. config.yaml: cities), поэтому фан-аута по городам нет."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from decouple import Config, RepositoryEnv
from avito_bridge.avito.client import AvitoClient, status_by_ad_id
from avito_bridge.feed.ad_id import make_ad_id
from avito_studio.catalog_service import CatalogRow

CITY_ID = "simferopol"


@dataclass
class RowAvitoStatus:
    avito_status: str | None
    url: str | None


def build_client(bridge_root: Path) -> AvitoClient:
    cfg = Config(RepositoryEnv(str(Path(bridge_root) / ".env")))
    return AvitoClient(client_id=cfg("AVITO_CLIENT_ID"), client_secret=cfg("AVITO_CLIENT_SECRET"))


def match_statuses(rows: list[CatalogRow], items: list[dict]) -> dict[str, RowAvitoStatus]:
    by_ad_id = status_by_ad_id(items)
    result: dict[str, RowAvitoStatus] = {}
    for row in rows:
        supplier_sku = f"{row.source}:{row.representative_nc}"
        ad_id = make_ad_id(supplier_sku, CITY_ID)
        item = by_ad_id.get(ad_id)
        result[row.key] = RowAvitoStatus(
            avito_status=item.get("avito_status") if item else None,
            url=item.get("url") if item else None)
    return result


def fetch_statuses(bridge_root: Path, rows: list[CatalogRow]) -> dict[str, RowAvitoStatus]:
    client = build_client(bridge_root)
    items = client.last_successful_items()
    return match_statuses(rows, items)
