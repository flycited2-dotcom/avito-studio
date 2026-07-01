"""Редактирование avito-bridge/config/config.yaml с сохранением комментариев и форматирования
(ruamel round-trip), в отличие от apply_inbox.py (который только вставляет строки регэкспом
и не умеет убирать записи — а «полное управление каталогом» требует и включать, и выключать серию)."""
from __future__ import annotations
from pathlib import Path
from ruamel.yaml import YAML
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

    def save(self) -> None:
        with self.path.open("w", encoding="utf-8", newline="\n") as f:
            _yaml.dump(self.data, f)
