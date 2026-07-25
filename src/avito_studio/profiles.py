"""Реестр профилей бизнеса для студии: какой YAML в avito-bridge читать/править локально
и с каким --config звать catalog_export на сервере. Новый бизнес = строка здесь +
YAML-профиль в avito-bridge (см. docs/specs/2026-07-04-universal-business-profiles.md)."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    key: str          # машинное имя (= profile.name в YAML движка)
    label: str        # подпись в комбо-боксе тулбара
    config_rel: str   # путь к YAML относительно корня avito-bridge (одинаков локально и на VPS)
    local_catalog: bool = False  # источник доступен только на Windows до деплоя прайса на VPS
    publish_enabled: bool = True
    publish_block_reason: str = ""
    cards_enabled: bool = False


PROFILES: list[Profile] = [
    Profile(
        "conditioners",
        "Кондиционеры",
        "config/config.yaml",
        cards_enabled=True,
    ),
    Profile("wreaths", "Венки", "profiles/wreaths.yaml"),
    Profile(
        "appliances",
        "Бытовая техника",
        "profiles/appliances.yaml",
        local_catalog=True,
        publish_enabled=False,
        publish_block_reason=(
            "Профиль бытовой техники остаётся безопасным предпросмотром: "
            "для основного аккаунта нужен объединённый фид с кондиционерами и "
            "подтверждение категорий/наценок. На сервер ничего не отправлено."
        ),
    ),
    Profile("carver", "Генераторы CARVER", "profiles/carver.yaml", local_catalog=True),
]
