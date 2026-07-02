"""Собирает строки таблицы каталога: фактические данные БД (с сервера, через SSH catalog_export)
+ локальный статус публикации (config.yaml, LocalConfig)."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from avito_studio.local_config import LocalConfig

REMOTE_EXPORT_CMD = ("cd /opt/avito-bridge && export PYTHONPATH=src && "
                     ".venv/bin/python -m avito_bridge.catalog_export")


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


def fetch_catalog(ssh, local_cfg: LocalConfig) -> list[CatalogRow]:
    """ssh — любой объект с методом .run(cmd) -> str (см. SshClient)."""
    data = json.loads(ssh.run(REMOTE_EXPORT_CMD))
    rows = []
    for g in data["series"]:
        rows.append(CatalogRow(
            key=g["key"], source=g["source"], brand=g["brand"], series=g["series"],
            sizes=_sizes_label(g["members"]), stock_total=g["stock_total"],
            has_card=g["has_card"], forced=g["forced"],
            selected=local_cfg.is_selected(g["key"]),
            # аномальная серия без членов не должна ронять всё «Обновить» целиком
            representative_nc=g["members"][0]["nc_code"] if g["members"] else "",
            price_range=_price_range_label(g["members"])))
    return rows
