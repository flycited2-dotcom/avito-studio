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
        # insert(0, ...) — а не обычное присваивание в конец: комментарий про manual_photos
        # в реальном config.yaml физически приклеен (склеен ruamel) к ПОСЛЕДНЕМУ существующему
        # ключу force_include; добавление в конец раздвигает эту склейку и комментарий "уезжает"
        # внутрь force_include. Вставка в начало не трогает последний ключ и его комментарий.
        self.data["catalog"]["force_include"].insert(0, DQ(nc_code), entry)

    def _catalog_map(self, name: str) -> CommentedMap:
        """Возвращает вложенную мапу catalog.<name>, создавая её при первом обращении.
        insert(0, ...) — а не обычное присваивание в конец: комментарий перед СЛЕДУЮЩЕЙ секцией
        (напр. cards:) физически приклеен ruamel к ПОСЛЕДНЕМУ существующему ключу catalog;
        добавление нового ключа в конец раздвигает эту склейку. Вставка в начало не трогает её."""
        catalog = self.data["catalog"]
        if name not in catalog:
            catalog.insert(0, name, CommentedMap())
        return catalog[name]

    def get_manual_price(self, nc_code: str) -> int | None:
        return self.data.get("catalog", {}).get("manual_price_override", {}).get(nc_code)

    def set_manual_price(self, nc_code: str, price: int) -> None:
        overrides = self._catalog_map("manual_price_override")
        if nc_code in overrides:
            overrides[nc_code] = price
        else:
            overrides.insert(0, DQ(nc_code), price)

    def remove_manual_price(self, nc_code: str) -> None:
        overrides = self.data.get("catalog", {}).get("manual_price_override")
        if overrides and nc_code in overrides:
            del overrides[nc_code]

    def get_card_brief(self, nc_code: str) -> str | None:
        return self.data.get("catalog", {}).get("manual_card_brief", {}).get(nc_code)

    def set_card_brief(self, nc_code: str, text: str) -> None:
        overrides = self._catalog_map("manual_card_brief")
        if nc_code in overrides:
            overrides[nc_code] = DQ(text)
        else:
            overrides.insert(0, DQ(nc_code), DQ(text))

    def remove_card_brief(self, nc_code: str) -> None:
        overrides = self.data.get("catalog", {}).get("manual_card_brief")
        if overrides and nc_code in overrides:
            del overrides[nc_code]

    def get_manual_photo(self, nc_code: str) -> str | None:
        return self.data.get("catalog", {}).get("manual_photos", {}).get(nc_code)

    def set_manual_photo(self, nc_code: str, url: str) -> None:
        self.data["catalog"].setdefault("manual_photos", {})[nc_code] = DQ(url)

    def remove_manual_photo(self, nc_code: str) -> None:
        photos = self.data.get("catalog", {}).get("manual_photos")
        if photos and nc_code in photos:
            del photos[nc_code]

    def save(self) -> None:
        with self.path.open("w", encoding="utf-8", newline="\n") as f:
            _yaml.dump(self.data, f)
