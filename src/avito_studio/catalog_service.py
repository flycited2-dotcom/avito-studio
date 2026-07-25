"""Собирает строки таблицы каталога: фактические данные БД (с сервера, через SSH catalog_export)
+ локальный статус публикации (config.yaml, LocalConfig)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from avito_studio.local_config import LocalConfig

REMOTE_EXPORT_CMD = ("cd /opt/avito-bridge && export PYTHONPATH=src && "
                     ".venv/bin/python -m avito_bridge.catalog_export")


def export_cmd(config_rel: str = "config/config.yaml") -> str:
    """Команда экспорта каталога ВЫБРАННОГО профиля (селектор в тулбаре студии)."""
    return f"{REMOTE_EXPORT_CMD} --config {config_rel}"


@dataclass(frozen=True)
class CatalogMember:
    nc_code: str
    current_price: int | None
    cost: int | None
    price_ok: bool
    forced: bool
    supplier_sku: str = ""
    product_kind: str = ""
    ad_id_revision: int = 0


@dataclass
class CatalogRow:
    key: str
    source: str
    brand: str
    series: str
    sizes: str
    stock_total: int
    has_card: bool
    forced: bool
    selected: bool
    representative_nc: str = ""
    price_range: str = "—"
    avito_status: str | None = None
    members: tuple[CatalogMember, ...] = ()
    ad_supplier_sku: str = ""
    ad_id_revision: int = 0


def leading_price(price_range: str) -> int | None:
    """Первое число из строки вида "25990–27990 ₽" / "19990 ₽"; None для "—".
    Формат price_range задаётся здесь же (_price_range_label) — и парсер живёт рядом."""
    m = re.match(r"(\d+)", price_range)
    return int(m.group(1)) if m else None


def _sizes_label(members: list[dict]) -> str:
    sizes = sorted({m["btu_calc"] for m in members if m.get("btu_calc")})
    if not sizes:
        return "—"
    return "/".join(str(int(s)) for s in sizes) + " тыс. BTU"


def _price_range_label(members: list[dict]) -> str:
    prices = sorted({m["price"] for m in members if m.get("price_ok") and m.get("price") is not None})
    if not prices:
        return "—"
    if len(prices) == 1:
        return f"{prices[0]} ₽"
    return f"{prices[0]}–{prices[-1]} ₽"


def fetch_catalog(ssh, local_cfg: LocalConfig,
                  config_rel: str = "config/config.yaml") -> list[CatalogRow]:
    """ssh — любой объект с методом .run(cmd) -> str (см. SshClient).
    config_rel — YAML профиля для catalog_export (default: боевой кондиционерный)."""
    data = json.loads(ssh.run(export_cmd(config_rel)))
    return _rows_from_data(data, local_cfg)


def _rows_from_data(data: dict, local_cfg: LocalConfig) -> list[CatalogRow]:
    rows = []
    for g in data["series"]:
        rows.append(CatalogRow(
            key=g["key"], source=g["source"], brand=g["brand"], series=g["series"],
            sizes=_sizes_label(g["members"]), stock_total=g["stock_total"],
            has_card=g["has_card"], forced=g["forced"],
            selected=local_cfg.is_selected(g["key"]),
            # аномальная серия без членов не должна ронять всё «Обновить» целиком
            representative_nc=g["members"][0]["nc_code"] if g["members"] else "",
            price_range=_price_range_label(g["members"]),
            ad_supplier_sku=str(g.get("ad_supplier_sku") or ""),
            ad_id_revision=int(g.get("ad_id_revision") or 0),
            members=tuple(CatalogMember(
                nc_code=str(member.get("nc_code", "")),
                current_price=member.get("price"),
                cost=member.get("cost"),
                price_ok=bool(member.get("price_ok")),
                forced=bool(member.get("forced")),
                supplier_sku=str(member.get("supplier_sku") or ""),
                product_kind=str(member.get("product_kind") or ""),
                ad_id_revision=int(member.get("ad_id_revision") or 0),
            ) for member in g["members"])))
    return rows


def fetch_local_catalog(config_path, local_cfg: LocalConfig) -> list[CatalogRow]:
    """Каталог локального XLS-профиля без предварительного деплоя прайса на VPS."""
    from avito_bridge.catalog_export import build_catalog_json
    from avito_bridge.config import load_config
    from avito_bridge.ingest.sources import fetch_profile_offers

    cfg = load_config(config_path)
    offers = fetch_profile_offers(cfg)
    return _rows_from_data(build_catalog_json(offers, cfg), local_cfg)
