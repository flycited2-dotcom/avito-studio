"""Собирает строки таблицы каталога: фактические данные БД (с сервера, через SSH catalog_export)
+ локальный статус публикации (config.yaml, LocalConfig)."""
from __future__ import annotations
import json
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


def _sizes_label(members: list[dict]) -> str:
    sizes = sorted({m["btu_calc"] for m in members if m.get("btu_calc")})
    if not sizes:
        return "—"
    return "/".join(str(int(s)) for s in sizes) + " тыс. BTU"


def fetch_catalog(ssh, local_cfg: LocalConfig) -> list[CatalogRow]:
    """ssh — любой объект с методом .run(cmd) -> str (см. SshClient)."""
    data = json.loads(ssh.run(REMOTE_EXPORT_CMD))
    rows = []
    for g in data["series"]:
        rows.append(CatalogRow(
            key=g["key"], source=g["source"], brand=g["brand"], series=g["series"],
            sizes=_sizes_label(g["members"]), stock_total=g["stock_total"],
            has_card=g["has_card"], forced=g["forced"],
            selected=local_cfg.is_selected(g["key"])))
    return rows
