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


PROFILES: list[Profile] = [
    Profile("conditioners", "Кондиционеры", "config/config.yaml"),
    Profile("wreaths", "Венки", "profiles/wreaths.yaml"),
]
