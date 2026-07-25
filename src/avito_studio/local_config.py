"""Редактирование avito-bridge/config/config.yaml с сохранением комментариев и форматирования
(ruamel round-trip), в отличие от apply_inbox.py (который только вставляет строки регэкспом
и не умеет убирать записи — а «полное управление каталогом» требует и включать, и выключать серию)."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ

from avito_studio.atomic_io import atomic_write_yaml

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096   # не переносить длинные строки при сохранении
# Без этого ruamel при ЛЮБОМ save() сбрасывает отступ последовательностей под ключом
# (напр. "    - x" → "- x"), давая огромный шумный diff даже без реальных правок.
# offset=2 — стиль, уже используемый в config.yaml ("catalog:\n  selected_series:\n    - x").
_yaml.indent(mapping=2, sequence=4, offset=2)

NONE_SELECTED = "__none__"


class LocalConfig:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = _yaml.load(self.path.read_text(encoding="utf-8"))
        self.selected_series()

    def selected_series(self) -> list[str]:
        selected = list(
            self.data.get("catalog", {}).get("selected_series") or []
        )
        if NONE_SELECTED in selected and selected != [NONE_SELECTED]:
            raise ValueError(
                "catalog.selected_series: маркер '__none__' допустим только "
                "как единственное значение"
            )
        return selected

    def is_selected(self, key: str) -> bool:
        selected = self.selected_series()
        if not selected:
            return True
        if NONE_SELECTED in selected:
            return False
        return key in selected

    def set_selected(self, key: str, selected: bool) -> None:
        """Set one key while keeping the all/none encoding fail-closed.

        An empty list means "all" to avito-bridge, while ``__none__`` means
        "none".  Deselecting from the implicit-all state cannot express a
        one-item exclusion, so it safely becomes "none"; callers that know the
        complete catalog should use :meth:`replace_selected` for an exact set.
        """
        seq = self._selection_seq()
        if selected:
            if not seq:
                return  # already selected by the implicit-all state
            if NONE_SELECTED in seq:
                seq.clear()
            if key not in seq:
                seq.append(DQ(key))
            return

        if not seq:
            seq.append(DQ(NONE_SELECTED))
        elif NONE_SELECTED in seq:
            return
        elif key in seq:
            seq.remove(key)
            if not seq:
                seq.append(DQ(NONE_SELECTED))

    def replace_selected(self, keys: Iterable[str]) -> None:
        """Store an exact whitelist; an empty iterable is encoded as "none"."""
        normalized: list[str] = []
        seen: set[str] = set()
        for value in keys:
            key = str(value)
            if not key or key == NONE_SELECTED or key in seen:
                continue
            seen.add(key)
            normalized.append(key)
        seq = self._selection_seq()
        seq.clear()
        if normalized:
            seq.extend(DQ(key) for key in normalized)
        else:
            seq.append(DQ(NONE_SELECTED))

    def select_all(self) -> None:
        """Use avito-bridge's canonical implicit-all representation."""
        self._selection_seq().clear()

    def _selection_seq(self) -> CommentedSeq:
        catalog = self.data.setdefault("catalog", CommentedMap())
        seq = catalog.get("selected_series")
        if not isinstance(seq, list):
            seq = CommentedSeq()
            catalog["selected_series"] = seq
        return seq

    def get_force_price(self, nc_code: str) -> int | None:
        entry = self.data.get("catalog", {}).get("force_include", {}).get(nc_code)
        return entry.get("price") if isinstance(entry, dict) else None

    def has_force_include(self, nc_code: str) -> bool:
        return nc_code in (self.data.get("catalog", {}).get("force_include", {}) or {})

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

    def get_manual_product(self, manual_id: str) -> dict | None:
        return self.data.get("catalog", {}).get("manual_products", {}).get(manual_id)

    def get_manual_product_price(self, manual_id: str) -> int | None:
        entry = self.get_manual_product(manual_id)
        if not isinstance(entry, dict):
            return None
        value = entry.get("price")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)

    def get_manual_product_photos(self, manual_id: str) -> list[str]:
        entry = self.get_manual_product(manual_id)
        if not isinstance(entry, dict):
            return []
        value = entry.get("photos")
        if not isinstance(value, (list, tuple)):
            return []
        return [str(url).strip() for url in value if str(url).strip()]

    def get_manual_product_description(self, manual_id: str) -> str:
        entry = self.get_manual_product(manual_id)
        if not isinstance(entry, dict):
            return ""
        return str(entry.get("description") or "").strip()

    def add_manual_product(self, manual_id: str, spec: dict) -> None:
        """Добавить товар, которого нет в БД поставщика, под стабильным ID приложения."""
        products = self._catalog_map("manual_products")
        if manual_id in products:
            raise ValueError(
                "Такой ручной товар уже существует. Откройте его в каталоге для редактирования.")
        entry = CommentedMap(spec)
        # Читаемый многострочный YAML: это полноценная карточка, а не короткий override.
        entry.fa.set_block_style()
        products.insert(0, DQ(manual_id), entry)

    def _manual_product_entry(self, manual_id: str) -> dict:
        entry = self.get_manual_product(manual_id)
        if not isinstance(entry, dict):
            raise KeyError(f"Ручной товар {manual_id!r} не найден")
        return entry

    def set_manual_product_price(self, manual_id: str, price: int) -> None:
        """Change the sale price of an existing fully manual product."""
        if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
            raise ValueError("Цена ручного товара должна быть целым числом больше нуля")
        self._manual_product_entry(manual_id)["price"] = price

    def set_manual_product_photos(self, manual_id: str, photos: list[str] | tuple[str, ...]) -> None:
        """Replace photos of an existing fully manual product."""
        if isinstance(photos, (str, bytes)):
            raise TypeError("Фотографии ручного товара должны быть списком URL")
        normalized = [str(url).strip() for url in photos if str(url).strip()]
        if not normalized:
            raise ValueError("У ручного товара должна остаться хотя бы одна фотография")
        self._manual_product_entry(manual_id)["photos"] = CommentedSeq(
            DQ(url) for url in normalized)

    def set_manual_product_description(self, manual_id: str, description: str) -> None:
        """Set or clear the optional description of a fully manual product."""
        entry = self._manual_product_entry(manual_id)
        normalized = str(description).strip()
        if normalized:
            entry["description"] = DQ(normalized)
        else:
            entry.pop("description", None)

    def remove_manual_product(self, manual_id: str) -> bool:
        """Remove a fully manual product.  Returns whether it existed."""
        products = self.data.get("catalog", {}).get("manual_products")
        if not products or manual_id not in products:
            return False
        del products[manual_id]
        return True

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

    def get_publication_settings(self) -> dict:
        """Return the editable Avito publication settings of the active profile.

        The settings intentionally live next to the feed/pricing settings in the
        profile YAML.  This keeps them profile-specific (CARVER cannot inherit a
        conditioner category by accident) while the GUI remains the single place
        a user needs to edit them.
        """
        feed = self.data.get("feed", {}) or {}
        base_tags = feed.get("base_tags", {}) or {}
        pricing = self.data.get("pricing", {}) or {}
        return {
            "category": str(base_tags.get("Category", "") or ""),
            "goods_type": str(base_tags.get("GoodsType", "") or ""),
            "goods_subtype": str(base_tags.get("GoodsSubType", "") or ""),
            "markup_pct": float(pricing.get("default_markup_pct", 0) or 0),
            "rounding": str(pricing.get("rounding", "none") or "none"),
            "price_confirmed": bool(pricing.get("price_confirmed", False)),
        }

    def set_publication_settings(
        self,
        *,
        category: str,
        goods_type: str,
        goods_subtype: str,
        markup_pct: float,
        rounding: str,
        price_confirmed: bool,
    ) -> None:
        """Persist category and pricing choices made in the publication dialog."""
        feed = self.data.setdefault("feed", CommentedMap())
        base_tags = feed.get("base_tags")
        if not isinstance(base_tags, dict):
            base_tags = CommentedMap()
            feed["base_tags"] = base_tags
        base_tags["Category"] = DQ(category.strip())
        base_tags["GoodsType"] = DQ(goods_type.strip())
        base_tags["GoodsSubType"] = DQ(goods_subtype.strip())

        pricing = self.data.setdefault("pricing", CommentedMap())
        normalized_markup = round(float(markup_pct), 1)
        pricing["default_markup_pct"] = (
            int(normalized_markup)
            if normalized_markup.is_integer() else normalized_markup
        )
        pricing["rounding"] = DQ(rounding)
        pricing["price_confirmed"] = bool(price_confirmed)

    def get_source_path(self) -> str:
        profile = self.data.get("profile", {}) or {}
        options = profile.get("source_options", {}) or {}
        return str(options.get("path", "") or "")

    def set_source_path(
        self,
        path: Path,
        *,
        relative_to: Path | None = None,
    ) -> None:
        """Set the source file path, optionally relative to a portable root."""
        profile = self.data.setdefault("profile", CommentedMap())
        options = profile.get("source_options")
        if not isinstance(options, dict):
            options = CommentedMap()
            profile["source_options"] = options
        resolved = Path(path).resolve()
        if relative_to is None:
            stored_path = str(resolved)
        else:
            root = Path(relative_to).resolve()
            try:
                stored_path = resolved.relative_to(root).as_posix()
            except ValueError as exc:
                raise ValueError(
                    f"Путь источника {resolved} находится вне корня {root}"
                ) from exc
        options["path"] = DQ(stored_path)

    def save(self) -> None:
        self.selected_series()
        atomic_write_yaml(self.path, self.data, _yaml)
