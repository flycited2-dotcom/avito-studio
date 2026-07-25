"""Сопоставление наших серий с реальным статусом объявления на Avito.

Ключ сопоставления: avito_bridge.feed.ad_id.make_ad_id(supplier_sku, city_id) — тот же хэш,
что Avito возвращает как ad_id в отчётах автозагрузки (подтверждено живым запросом). У нас всегда
 ОДИН город (см. config.yaml: cities), поэтому фан-аута по городам нет."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from avito_bridge.avito.client import AvitoClient, status_by_ad_id
from avito_bridge.feed.ad_id import make_ad_id
from decouple import Config, RepositoryEnv, UndefinedValueError

from avito_studio.catalog_service import CatalogRow

CITY_ID = "simferopol"
_PROFILE_SUFFIXES = {
    "conditioners": "",
    "wreaths": "_WREATHS",
    "carver": "_CARVER",
    "appliances": "_APPLIANCES",
}


@dataclass
class RowAvitoStatus:
    avito_status: str | None
    url: str | None


def credential_names(profile_key: str) -> tuple[str, str]:
    """Return the two credential names owned by exactly one profile."""
    try:
        suffix = _PROFILE_SUFFIXES[profile_key]
    except KeyError as exc:
        raise ValueError(f"Неизвестный профиль Avito: {profile_key!r}") from exc
    return f"AVITO_CLIENT_ID{suffix}", f"AVITO_CLIENT_SECRET{suffix}"


def load_credentials(bridge_root: Path, profile_key: str) -> tuple[str, str]:
    """Load profile credentials from process env, then an optional local .env."""
    client_id_name, client_secret_name = credential_names(profile_key)
    env_path = Path(bridge_root) / ".env"
    repository = Config(RepositoryEnv(str(env_path))) if env_path.is_file() else None

    def read(name: str) -> str:
        value = os.environ.get(name)
        if value is None and repository is not None:
            try:
                value = repository(name)
            except UndefinedValueError:
                value = None
        if not value or not value.strip():
            raise ValueError(f"Учетные данные {name} не настроены")
        return value.strip()

    return read(client_id_name), read(client_secret_name)


def build_client(
    bridge_root: Path, profile_key: str = "conditioners"
) -> AvitoClient:
    client_id, client_secret = load_credentials(bridge_root, profile_key)
    return AvitoClient(
        client_id=client_id,
        client_secret=client_secret,
    )


def match_statuses(rows: list[CatalogRow], items: list[dict]) -> dict[str, RowAvitoStatus]:
    by_ad_id = status_by_ad_id(items)
    result: dict[str, RowAvitoStatus] = {}
    for row in rows:
        member = row.members[0] if row.members else None
        supplier_sku = (
            row.ad_supplier_sku
            or (member.supplier_sku if member is not None and member.supplier_sku else "")
            or f"{row.source}:{row.representative_nc}"
        )
        revision = (
            row.ad_id_revision
            if row.ad_supplier_sku
            else member.ad_id_revision if member is not None else 0
        )
        ad_id = make_ad_id(supplier_sku, CITY_ID, revision=revision)
        item = by_ad_id.get(ad_id)
        result[row.key] = RowAvitoStatus(
            avito_status=item.get("avito_status") if item else None,
            url=item.get("url") if item else None)
    return result


def fetch_statuses(
    bridge_root: Path,
    rows: list[CatalogRow],
    profile_key: str = "conditioners",
) -> dict[str, RowAvitoStatus]:
    client = build_client(bridge_root, profile_key)
    try:
        items = client.last_successful_items()
    finally:
        client.close()
    return match_statuses(rows, items)
