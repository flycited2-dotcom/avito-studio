"""Редактирование avito-bridge/config/config.yaml с сохранением комментариев и форматирования
(ruamel round-trip), в отличие от apply_inbox.py (который только вставляет строки регэкспом
и не умеет убирать записи — а «полное управление каталогом» требует и включать, и выключать серию)."""
from __future__ import annotations
from pathlib import Path
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096   # не переносить длинные строки при сохранении
# Без этого ruamel при ЛЮБОМ save() сбрасывает отступ последовательностей под ключом
# (напр. "    - x" → "- x"), давая огромный шумный diff даже без реальных правок.
# offset=2 — стиль, уже используемый в config.yaml ("catalog:\n  selected_series:\n    - x").
_yaml.indent(mapping=2, sequence=4, offset=2)


class LocalConfig:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = _yaml.load(self.path.read_text(encoding="utf-8"))

    def selected_series(self) -> list[str]:
        return list(self.data.get("catalog", {}).get("selected_series") or [])

    def is_selected(self, key: str) -> bool:
        return key in self.selected_series()

    def set_selected(self, key: str, selected: bool) -> None:
        seq = self.data["catalog"]["selected_series"]
        if selected and key not in seq:
            seq.append(DQ(key))    # в кавычках — как все остальные записи в файле
        elif not selected and key in seq:
            seq.remove(key)

    def get_force_price(self, nc_code: str) -> int | None:
        entry = self.data.get("catalog", {}).get("force_include", {}).get(nc_code)
        return entry.get("price") if isinstance(entry, dict) else None

    def set_force_price(self, nc_code: str, price: int) -> None:
        self.data["catalog"]["force_include"][nc_code]["price"] = price

    def add_force_include(self, nc_code: str, price: int, series: str | None = None) -> None:
        # CommentedMap + set_flow_style() — иначе новая запись рендерится многострочным блоком,
        # а не inline "{ price: ..., series: ... }" как все соседние записи (см. Task 1 Step 5 плана).
        entry = CommentedMap({"price": price})
        if series:
            entry["series"] = DQ(series)
        entry.fa.set_flow_style()
        self.data["catalog"]["force_include"][DQ(nc_code)] = entry

    def get_manual_photo(self, nc_code: str) -> str | None:
        return self.data.get("catalog", {}).get("manual_photos", {}).get(nc_code)

    def set_manual_photo(self, nc_code: str, url: str) -> None:
        self.data["catalog"].setdefault("manual_photos", {})[nc_code] = DQ(url)

    def save(self) -> None:
        with self.path.open("w", encoding="utf-8", newline="\n") as f:
            _yaml.dump(self.data, f)
