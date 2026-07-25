import pytest

from avito_studio.local_config import NONE_SELECTED, LocalConfig

FIXTURE = """\
# комментарий, который должен выжить
cities:
  - { id: "simferopol", name: "Симферополь", avito_location: "Крым" }
pricing:
  default_markup_pct: 5
catalog:
  force_include:
    "НС-1": { price: 18990, series: "ACE-07" }
  manual_photos:
    "НС-2": "https://x/2.jpg"
  selected_series:
    - "breeze|funai|sensei 2.0"
    - "daichi|midea|изи"
"""


def _write(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(FIXTURE, encoding="utf-8")
    return p


def test_is_selected_reflects_yaml(tmp_path):
    cfg = LocalConfig(_write(tmp_path))
    assert cfg.is_selected("breeze|funai|sensei 2.0") is True
    assert cfg.is_selected("nope|not|there") is False


def test_set_selected_true_adds_and_saves(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.set_selected("rusklimat|ballu|tessey dc", True)
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.is_selected("rusklimat|ballu|tessey dc") is True
    assert "комментарий, который должен выжить" in path.read_text(encoding="utf-8")


def test_set_selected_false_removes_and_is_idempotent(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.set_selected("daichi|midea|изи", False)
    cfg.set_selected("daichi|midea|изи", False)   # повторный вызов не должен падать
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.is_selected("daichi|midea|изи") is False
    assert reloaded.is_selected("breeze|funai|sensei 2.0") is True   # остальное не тронуто


def test_selected_series_lists_all(tmp_path):
    cfg = LocalConfig(_write(tmp_path))
    assert set(cfg.selected_series()) == {"breeze|funai|sensei 2.0", "daichi|midea|изи"}


def test_empty_selection_means_all_for_bridge_backward_compatibility(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("catalog:\n  selected_series: []\n", encoding="utf-8")
    cfg = LocalConfig(path)
    assert cfg.is_selected("any|existing|series") is True


def test_none_sentinel_means_no_series(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('catalog:\n  selected_series: ["__none__"]\n', encoding="utf-8")
    cfg = LocalConfig(path)
    assert cfg.is_selected("__none__") is False
    assert cfg.is_selected("any|existing|series") is False


def test_mixed_none_sentinel_and_explicit_keys_is_rejected_on_load(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        'catalog:\n  selected_series: ["__none__", "explicit-key"]\n',
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="'__none__' допустим только как единственное значение",
    ):
        LocalConfig(path)


def test_mixed_none_sentinel_and_explicit_keys_is_rejected_before_save(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.data["catalog"]["selected_series"].insert(0, NONE_SELECTED)

    with pytest.raises(
        ValueError,
        match="'__none__' допустим только как единственное значение",
    ):
        cfg.save()

    assert NONE_SELECTED not in path.read_text(encoding="utf-8")


def test_replace_selected_stores_exact_deduplicated_whitelist(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.replace_selected(["new|a", "new|a", NONE_SELECTED, "", "new|b"])
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.selected_series() == ["new|a", "new|b"]
    assert reloaded.is_selected("new|a") is True
    assert reloaded.is_selected("breeze|funai|sensei 2.0") is False


def test_replace_selected_empty_is_encoded_as_none_not_all(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.replace_selected([])
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.selected_series() == [NONE_SELECTED]
    assert reloaded.is_selected("anything") is False


def test_removing_last_explicit_selection_becomes_none(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('catalog:\n  selected_series: ["only"]\n', encoding="utf-8")
    cfg = LocalConfig(path)
    cfg.set_selected("only", False)
    assert cfg.selected_series() == [NONE_SELECTED]
    assert cfg.is_selected("another") is False


def test_select_all_uses_empty_bridge_representation(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.select_all()
    assert cfg.selected_series() == []
    assert cfg.is_selected("anything") is True


def test_save_preserves_sequence_indentation_style(tmp_path):
    """Без явного yaml.indent(...) ruamel сбрасывает отступ списка при КАЖДОМ save() —
    даёт огромный шумный diff, даже когда правишь одну строку. Список должен остаться
    с отступом в 4 пробела (стиль, уже используемый в реальном config.yaml)."""
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.set_selected("new|entry|x", True)
    cfg.save()
    text = path.read_text(encoding="utf-8")
    assert '    - "breeze|funai|sensei 2.0"' in text
    assert '    - "new|entry|x"' in text


def test_get_force_price_reads_existing_entry(tmp_path):
    cfg = LocalConfig(_write(tmp_path))
    assert cfg.get_force_price("НС-1") == 18990
    assert cfg.get_force_price("НС-999") is None


def test_set_force_price_updates_existing_entry_and_saves(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.set_force_price("НС-1", 20990)
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_force_price("НС-1") == 20990
    assert "ACE-07" in path.read_text(encoding="utf-8")   # серия у записи не потерялась


def test_has_force_include_distinguishes_existing_entry(tmp_path):
    cfg = LocalConfig(_write(tmp_path))
    assert cfg.has_force_include("НС-1") is True
    assert cfg.has_force_include("НС-999") is False


def test_manual_photo_get_set_roundtrip(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    assert cfg.get_manual_photo("НС-9") is None
    cfg.set_manual_photo("НС-9", "https://splithome.ru/static/manual-photos/НС-9.jpg")
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_manual_photo("НС-9") == "https://splithome.ru/static/manual-photos/НС-9.jpg"
    assert reloaded.get_manual_photo("НС-2") == "https://x/2.jpg"   # старая запись не потерялась


def test_add_force_include_new_entry_with_series(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.add_force_include("НС-777", 15990, series="Тестовая серия")
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_force_price("НС-777") == 15990
    text = path.read_text(encoding="utf-8")
    assert "НС-777" in text and "Тестовая серия" in text
    assert "НС-1" in text and "ACE-07" in text   # старая запись не потерялась


def test_add_force_include_without_series(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.add_force_include("НС-778", 9990)
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_force_price("НС-778") == 9990


def test_add_fully_manual_product_roundtrip(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.add_manual_product("manual-rc-gr28hn-deadbeef", {
        "brand": "ROYAL CLIMA", "title": "RCI-GR28HN",
        "series": "GRIDA Inverter", "category_id": 2,
        "btu": 9, "price": 26550, "stock": 1,
        "photos": ["https://x/manual.jpg"],
        "tech": {"Тип компрессора": "Инвертор"},
    })
    cfg.save()
    product = LocalConfig(path).get_manual_product("manual-rc-gr28hn-deadbeef")
    assert product["brand"] == "ROYAL CLIMA"
    assert product["price"] == 26550
    assert product["photos"] == ["https://x/manual.jpg"]


def test_duplicate_fully_manual_product_is_rejected(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    spec = {"brand": "B", "title": "T", "series": "S", "btu": 9, "price": 1}
    cfg.add_manual_product("manual-x", spec)
    with __import__("pytest").raises(ValueError, match="уже существует"):
        cfg.add_manual_product("manual-x", spec)


def test_edit_and_remove_fully_manual_product_roundtrip(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.add_manual_product("manual-x", {
        "brand": "B", "title": "T", "series": "S",
        "price": 100, "photos": ["https://x/old.jpg"],
    })
    cfg.set_manual_product_price("manual-x", 250)
    cfg.set_manual_product_photos(
        "manual-x", [" https://x/new-1.jpg ", "https://x/new-2.jpg"])
    cfg.set_manual_product_description("manual-x", " Новое описание ")
    cfg.save()

    product = LocalConfig(path).get_manual_product("manual-x")
    assert product["price"] == 250
    assert list(product["photos"]) == ["https://x/new-1.jpg", "https://x/new-2.jpg"]
    assert product["description"] == "Новое описание"
    reloaded = LocalConfig(path)
    assert reloaded.get_manual_product_price("manual-x") == 250
    assert reloaded.get_manual_product_photos("manual-x") == [
        "https://x/new-1.jpg",
        "https://x/new-2.jpg",
    ]
    assert reloaded.get_manual_product_description("manual-x") == "Новое описание"

    cfg = LocalConfig(path)
    cfg.set_manual_product_description("manual-x", " ")
    assert "description" not in cfg.get_manual_product("manual-x")
    assert cfg.remove_manual_product("manual-x") is True
    assert cfg.remove_manual_product("manual-x") is False
    cfg.save()
    assert LocalConfig(path).get_manual_product("manual-x") is None


@pytest.mark.parametrize("method,value,error", [
    ("set_manual_product_price", 0, ValueError),
    ("set_manual_product_price", True, ValueError),
    ("set_manual_product_photos", [], ValueError),
    ("set_manual_product_photos", "https://x/not-a-list.jpg", TypeError),
])
def test_manual_product_edit_rejects_invalid_values(tmp_path, method, value, error):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.add_manual_product("manual-x", {
        "brand": "B", "title": "T", "series": "S",
        "price": 100, "photos": ["https://x/old.jpg"],
    })
    with pytest.raises(error):
        getattr(cfg, method)("manual-x", value)


def test_manual_product_edit_rejects_unknown_id(tmp_path):
    cfg = LocalConfig(_write(tmp_path))
    with pytest.raises(KeyError, match="не найден"):
        cfg.set_manual_product_price("missing", 100)


def test_local_config_save_failure_preserves_previous_yaml(tmp_path, monkeypatch):
    path = _write(tmp_path)
    before = path.read_text(encoding="utf-8")
    cfg = LocalConfig(path)
    cfg.set_force_price("НС-1", 99999)

    def fail_write(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("avito_studio.local_config.atomic_write_yaml", fail_write)
    with pytest.raises(OSError, match="disk full"):
        cfg.save()
    assert path.read_text(encoding="utf-8") == before


# Реальный config.yaml: комментарий про manual_photos стоит СРАЗУ после последней записи
# force_include без пустой строки. ruamel склеивает такой комментарий с последним ключом —
# добавление в конец мапы (обычным присваиванием) "раздвигает" склейку и комментарий уезжает
# ВНУТРЬ force_include (перед новой записью, хотя семантически он про manual_photos).
FIXTURE_TRAILING_COMMENT = """\
catalog:
  force_include:
    "A": { price: 1, series: "s1" }   # comment A
    "B": { price: 2, series: "s2" }   # comment B
  # this comment belongs to manual_photos
  manual_photos:
    "X": "url"
"""


def test_add_force_include_does_not_disturb_trailing_comment_of_next_section(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(FIXTURE_TRAILING_COMMENT, encoding="utf-8")
    cfg = LocalConfig(path)
    cfg.add_force_include("C", 3, series="s3")
    cfg.save()
    text = path.read_text(encoding="utf-8")
    # комментарий должен остаться НЕПОСРЕДСТВЕННО перед "manual_photos:", а не между
    # force_include-записями
    assert "  # this comment belongs to manual_photos\n  manual_photos:" in text


def test_manual_price_get_set_remove_roundtrip(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    assert cfg.get_manual_price("НС-5") is None
    cfg.set_manual_price("НС-5", 24990)
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_manual_price("НС-5") == 24990
    reloaded.remove_manual_price("НС-5")
    reloaded.save()
    assert LocalConfig(path).get_manual_price("НС-5") is None


def test_remove_manual_price_is_idempotent_when_absent(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    cfg.remove_manual_price("НС-999")   # не должно падать, даже если секции ещё нет
    cfg.save()


def test_set_manual_price_new_entry_quoted_and_does_not_disturb_trailing_comment(tmp_path):
    """Тот же сценарий, что у add_force_include: manual_price_override — совсем новая секция,
    добавляется ПОСЛЕ selected_series, перед которым в реальном config.yaml (0-й отступ, как у
    самого cards:) стоит комментарий про следующий раздел (cards:). Ключ должен быть в кавычках,
    а комментарий — не сдвинут внутрь catalog."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "catalog:\n"
        "  selected_series:\n"
        "    - \"a|b|c\"\n"
        "# this comment belongs to cards\n"
        "cards:\n"
        "  enabled: true\n",
        encoding="utf-8")
    cfg = LocalConfig(path)
    cfg.set_manual_price("НС-42", 24990)
    cfg.save()
    text = path.read_text(encoding="utf-8")
    assert '"НС-42": 24990' in text
    assert "# this comment belongs to cards\ncards:" in text


def test_card_brief_get_set_remove_roundtrip(tmp_path):
    path = _write(tmp_path)
    cfg = LocalConfig(path)
    assert cfg.get_card_brief("НС-2") is None
    cfg.set_card_brief("НС-2", "Тихий, мощный, Wi-Fi")
    cfg.save()
    reloaded = LocalConfig(path)
    assert reloaded.get_card_brief("НС-2") == "Тихий, мощный, Wi-Fi"
    reloaded.remove_card_brief("НС-2")
    reloaded.save()
    assert LocalConfig(path).get_card_brief("НС-2") is None


def test_card_brief_new_entry_does_not_disturb_trailing_comment(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "catalog:\n"
        "  selected_series:\n"
        "    - \"a|b|c\"\n"
        "# this comment belongs to cards\n"
        "cards:\n"
        "  enabled: true\n",
        encoding="utf-8")
    cfg = LocalConfig(path)
    cfg.set_card_brief("НС-42", "Компактный, тихий")
    cfg.save()
    text = path.read_text(encoding="utf-8")
    assert '"НС-42": "Компактный, тихий"' in text
    assert "# this comment belongs to cards\ncards:" in text
