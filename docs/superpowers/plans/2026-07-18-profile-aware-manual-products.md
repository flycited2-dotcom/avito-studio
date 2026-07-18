# Profile-aware Manual Products Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Studio manual-product forms, stored characteristics, catalog presentation, and Bridge feed generation follow the active business profile for conditioners, CARVER, appliances, and wreaths.

**Architecture:** Studio receives a small schema registry keyed by `Profile.key`; the dialog renders the schema and stores a common manual-product contract plus profile-specific fields. Bridge replaces the conditioner-only loader with a generic `Offer` builder and combines manual offers with every configured source through one shared entry point used by both catalog export and production feed generation.

**Tech Stack:** Python 3.14, PySide6, pytest/pytest-qt, ruamel.yaml, pydantic, lxml, PyInstaller.

## Global Constraints

- Preserve legacy conditioner `catalog.manual_products` entries with `category_id`, `btu`, and `tech`.
- Do not include or modify the user's untracked `tests/test_pricing.py` in Studio commits.
- Manual product publication remains explicit; saving never deploys or publishes.
- Photo upload completes before local YAML mutation.
- Unknown profile keys fail closed and never render conditioner controls.
- Final verification requires complete Studio and Bridge suites, rebuilt EXE, and GUI smoke coverage for all four profiles.

## File map

### Avito Bridge

- Modify `src/avito_bridge/ingest/manual_products.py`: validate common/profile fields and build generic `Offer` objects.
- Modify `src/avito_bridge/ingest/sources.py`: add one `fetch_profile_offers(cfg)` composition point and remove Oasis-only manual injection.
- Modify `src/avito_bridge/__main__.py`: use the shared composition point.
- Modify `src/avito_bridge/catalog_export.py`: use the same composition point.
- Modify `tests/test_manual_products.py`: cover legacy conditioners and three generic profiles.
- Modify `tests/test_sources.py`: prove manual products append exactly once for every source.
- Modify `tests/test_builder.py`: prove generic Avito tags reach XML.

### Avito Studio

- Create `src/avito_studio/manual_product_forms.py`: profile schema dataclasses, presets, appliance group resolution, and pure validation/serialization helpers.
- Create `tests/test_manual_product_forms.py`: schema and serialization contract tests.
- Modify `src/avito_studio/add_forced_dialog.py`: render the active schema and characteristics table.
- Modify `tests/test_add_forced_dialog.py`: four-profile widget, validation, and YAML tests.
- Modify `src/avito_studio/catalog_table_model.py`: profile-aware headers.
- Modify `tests/test_catalog_table_model.py`: conditioner and per-item headers.
- Modify `src/avito_studio/main_window.py`: pass active profile, clear stale rows, and hide BTU column for per-item profiles.
- Modify `tests/test_main_window.py`: active-profile propagation and profile-switch state.

---

### Task 1: Generic Bridge manual-product contract

**Files:**
- Modify: `src/avito_bridge/ingest/manual_products.py`
- Test: `tests/test_manual_products.py`

**Interfaces:**
- Consumes: `AppConfig`, `Offer`, and `catalog.manual_products` mappings.
- Produces: `build_manual_offers(specs: dict | None, cfg: AppConfig) -> list[Offer]`.

- [ ] **Step 1: Write failing tests for legacy and generic products**

Add tests that construct minimal `AppConfig` values and assert:

```python
conditioner = build_manual_offers({"manual-ac": {
    "brand": "Ballu", "title": "BSAG-09", "series": "Eco",
    "category_id": 2, "btu": 9, "price": 30000, "stock": 1,
    "photos": ["https://i/ac.jpg"], "tech": {"Тип компрессора": "Инвертор"},
}}, conditioner_cfg)[0]
assert conditioner.category_id == 2 and conditioner.btu_calc == 9

carver = build_manual_offers({"manual-generator": {
    "brand": "CARVER", "title": "PPG-1900i", "group": "generator",
    "price": 43200, "stock": 1, "photos": ["https://i/g.jpg"],
    "description": "Компактный генератор.",
    "tech": {"Топливо": "Бензин"},
    "avito_tags": {"FuelType": "Бензин", "RatedPower": "1.7"},
}}, carver_cfg)[0]
assert carver.category_id is None and carver.btu_calc is None
assert carver.attrs["avito_tag:FuelType"] == "Бензин"
assert "Топливо: Бензин" in carver.attrs["desc_long"]
```

Also assert rejection of empty price/stock/photos, duplicate/empty identity, and unsafe Avito tag names.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manual_products.py -q` from the Bridge repository using the Studio virtualenv and Bridge `PYTHONPATH`.

Expected: import failure for `build_manual_offers`.

- [ ] **Step 3: Implement the generic builder**

Keep `build_manual_raw_products` for compatibility, but add:

```python
def build_manual_offers(specs: dict | None, cfg: AppConfig) -> list[Offer]:
    offers = []
    conditioner = cfg.profile_name in {"", "conditioners"}
    for manual_id, spec in _validated_specs(specs):
        category_id = _conditioner_category(spec, manual_id) if conditioner else None
        btu = _positive_number(spec.get("btu"), "btu", manual_id) if conditioner else None
        tech = _string_map(spec.get("tech"), manual_id, "tech")
        tags = _profile_tags(spec, cfg, manual_id)
        attrs = dict(tech)
        attrs.update({f"avito_tag:{key}": value for key, value in tags.items()})
        attrs["desc_long"] = _manual_description(spec, tech)
        offers.append(Offer(
            supplier_sku=f"manual:{manual_id}", source="manual",
            brand=str(spec["brand"]).strip(), model=str(spec["title"]).strip(),
            series=str(spec.get("series") or spec.get("group") or spec["title"]).strip(),
            category_id=category_id, btu_calc=btu, attrs=attrs,
            cost=None, stock=_positive_int(spec.get("stock", 1), "stock", manual_id),
            photos=_photo_list(spec, manual_id),
            price_override=Decimal(str(_positive_number(spec.get("price"), "price", manual_id))),
            forced=True,
        ))
    return offers
```

`_profile_tags` starts with `cfg.source_options["group_tags"][group]`, then overlays validated `spec["avito_tags"]`. `_manual_description` emits title, optional description, and deterministic `Характеристики:` rows.

- [ ] **Step 4: Run focused tests and verify GREEN**

Expected: all tests in `tests/test_manual_products.py` pass.

- [ ] **Step 5: Commit Bridge contract**

Commit only the builder and its tests with `feat: generalize manual products across profiles`.

### Task 2: Compose manual offers into every Bridge source

**Files:**
- Modify: `src/avito_bridge/ingest/sources.py`
- Modify: `src/avito_bridge/__main__.py`
- Modify: `src/avito_bridge/catalog_export.py`
- Modify: `tests/test_sources.py`

**Interfaces:**
- Consumes: `build_manual_offers(specs, cfg)` from Task 1.
- Produces: `fetch_profile_offers(cfg: AppConfig) -> list[Offer]`.

- [ ] **Step 1: Write a failing composition test**

Monkeypatch `SOURCES["fake"]` to return one supplier offer, provide one manual spec in `cfg.catalog.manual_products`, and assert `fetch_profile_offers(cfg)` returns exactly two offers with only one `manual:` SKU. Parameterize profile names `conditioners`, `wreaths`, `appliances`, and `carver` with valid profile-specific specs.

- [ ] **Step 2: Verify RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sources.py -q`.

Expected: import failure for `fetch_profile_offers`.

- [ ] **Step 3: Add the shared entry point and update callers**

```python
def fetch_profile_offers(cfg: AppConfig) -> list[Offer]:
    supplier = get_source(cfg.source)(cfg)
    manual = build_manual_offers(cfg.catalog.manual_products or {}, cfg)
    return [*supplier, *manual]
```

Remove `build_manual_raw_products` from `fetch_oasis`. Replace both `get_source(cfg.source)(cfg)` caller expressions in `__main__.py` and `catalog_export.py` with `fetch_profile_offers(cfg)`.

- [ ] **Step 4: Verify focused and full Bridge suites**

Run `tests/test_sources.py`, `tests/test_catalog_export.py`, then the complete Bridge suite. Expected: all pass with no duplicate manual offers.

- [ ] **Step 5: Commit Bridge integration**

Commit with `feat: include manual products in every profile source`.

### Task 3: Prove category tags and descriptions reach XML

**Files:**
- Modify: `tests/test_builder.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: generic `Offer.attrs` keys `avito_tag:<TagName>` and `desc_long`.
- Produces: regression evidence; no new production API unless a failure exposes a real gap.

- [ ] **Step 1: Add an end-to-end feed test**

Build a CARVER manual offer through `build_manual_offers`, run `run_cycle` with `grouping="per_item"` and `content.description_attr="desc_long"`, parse XML, and assert `FuelType`, `RatedPower`, title, description, price, and image.

- [ ] **Step 2: Run and diagnose RED or PASS**

If it passes immediately, retain it as integration coverage because Tasks 1–2 changed the contract. If it fails, make only the smallest production change needed in `feed/builder.py` or `content/render.py` and rerun.

- [ ] **Step 3: Commit integration coverage**

Commit with `test: cover manual profile feed generation`.

### Task 4: Studio profile form schema registry

**Files:**
- Create: `src/avito_studio/manual_product_forms.py`
- Create: `tests/test_manual_product_forms.py`

**Interfaces:**
- Produces: `FieldSpec`, `ManualFormSpec`, `form_spec(profile_key)`, `appliance_groups(local_cfg)`, `suggested_characteristics(profile_key, group)`, and `serialize_manual_product(...)`.

- [ ] **Step 1: Write failing pure tests**

Assert that:

```python
assert form_spec("conditioners").allow_nc_code is True
assert form_spec("carver").allow_nc_code is False
assert {f.key for f in form_spec("carver").fields} >= {
    "product_type", "fuel_type", "voltage", "rated_power", "maximum_power", "start_type"
}
assert "btu" not in {f.key for f in form_spec("appliances").fields}
assert "Мощность" in suggested_characteristics("appliances", "Миксеры")
assert "Скорость заморозки" in suggested_characteristics(
    "appliances", "Холодильники с нижней морозильной камерой")
with pytest.raises(KeyError):
    form_spec("unknown")
```

Test serialization for all four profiles, including CARVER Avito-tag mappings and appliance group persistence.

- [ ] **Step 2: Verify RED**

Run `.venv/Scripts/python.exe -m pytest tests/test_manual_product_forms.py -q` from Studio.

Expected: module import failure.

- [ ] **Step 3: Implement immutable schemas and pure serialization**

Use frozen dataclasses. Define four explicit schemas. Keep appliance suggestions in a small ordered mapping for mixers/blenders, refrigerators/freezers, washers/dryers, and a default (`Мощность`, `Ширина`, `Высота`, `Глубина`, `Цвет`). Serialization returns the exact YAML dictionary specified in the design and rejects duplicate characteristic names.

- [ ] **Step 4: Verify GREEN and commit**

Run the focused test and commit with `feat: define profile-aware manual product schemas`.

### Task 5: Render and save profile-aware Studio dialog

**Files:**
- Modify: `src/avito_studio/add_forced_dialog.py`
- Modify: `tests/test_add_forced_dialog.py`

**Interfaces:**
- Constructor becomes `AddForcedProductDialog(local_cfg: LocalConfig, ssh, profile: Profile = PROFILES[0], parent=None)` so existing callers/tests remain conditioner-compatible.
- Consumes Task 4 schema helpers.

- [ ] **Step 1: Add failing widget tests**

Create dialogs for each profile and assert the profile banner, НС tab visibility, field keys, and absence of BTU/inverter controls outside conditioners. Add an appliance test that changes group to `Миксеры`, verifies suggested rows, edits one row, changes group, and proves the edit is preserved.

- [ ] **Step 2: Verify RED**

Run `tests/test_add_forced_dialog.py -q`; expected failures show the constructor ignores profile and hard-coded conditioner widgets remain.

- [ ] **Step 3: Replace the hard-coded manual form with schema rendering**

Build common identity/price/stock controls once. Render schema controls into `self.profile_fields: dict[str, QWidget]`. Add `QTableWidget` for characteristics and add/remove buttons. For non-conditioners, remove the НС-code tab rather than merely disabling it. Use object names for deterministic GUI tests.

- [ ] **Step 4: Route validation and saving through serialization**

Replace BTU-specific `_update_save_enabled`, warning copy, and `_save_manual_product` with schema-aware value collection and `serialize_manual_product`. Keep the existing upload-first order and `LocalConfig.add_manual_product` call.

- [ ] **Step 5: Verify focused dialog tests and commit**

Run `tests/test_manual_product_forms.py tests/test_add_forced_dialog.py tests/test_ui_style_contract.py -q`. Commit with `feat: adapt manual product dialog to active profile`.

### Task 6: Profile-aware catalog state and headers

**Files:**
- Modify: `src/avito_studio/catalog_table_model.py`
- Modify: `src/avito_studio/main_window.py`
- Modify: `tests/test_catalog_table_model.py`
- Modify: `tests/test_main_window.py`

**Interfaces:**
- `CatalogTableModel(rows, per_item: bool = False)` selects `Серия/Типоразмеры` or `Товар/Характеристики` headers.
- `MainWindow._apply_profile_table(profile)` resets the model and BTU column visibility.

- [ ] **Step 1: Write failing model and window tests**

Assert per-item model header `Товар`; assert `_switch_profile` immediately replaces existing conditioner rows with an empty per-item model before refresh; assert `_open_add_forced_dialog` passes `win.profile` to the dialog.

- [ ] **Step 2: Verify RED**

Run the two focused test files and confirm failures are caused by fixed headers/stale model/missing constructor argument.

- [ ] **Step 3: Implement presentation state**

Give `CatalogTableModel` instance headers. In `_switch_profile`, save old selection, assign profile/config, call `_apply_profile_table(profile)`, then refresh. `_apply_profile_table` installs a fresh proxy source model and hides `COL_SIZES` for `profile.key != "conditioners"`. Pass `profile=self.profile` when opening the dialog.

- [ ] **Step 4: Verify focused and full Studio suites**

Run focused files, then all Studio tests. Expected: all pass, including the user's untracked pricing test without modifying it.

- [ ] **Step 5: Commit Studio integration**

Commit tracked production/tests only with `feat: switch manual product UI with business profile`.

### Task 7: Build, visual verification, and GitHub delivery

**Files:**
- Rebuild: `dist/AvitoContentStudio.exe`
- No source changes unless verification reveals a reproducible defect.

- [ ] **Step 1: Run final repository checks**

Run `git diff --check`, complete Bridge tests, and complete Studio tests. Record exact pass counts.

- [ ] **Step 2: Rebuild the executable**

Use the existing `avito_studio.spec`, Studio virtualenv, Studio `src`, and current Bridge `src`. Confirm PyInstaller exits `0`, the EXE timestamp changes, and calculate SHA-256.

- [ ] **Step 3: GUI smoke all profiles**

Launch the rebuilt app in an isolated smoke process. Open the manual dialog for each profile or use Qt offscreen construction tests to verify the banner, visible controls, НС tab behavior, and dialog responsiveness. Stop only the smoke process started by this task.

- [ ] **Step 4: Review diffs and repository status**

Ensure no credentials, local price paths, generated build folders, or user-owned untracked files are staged. Confirm Bridge and Studio commits contain only task files.

- [ ] **Step 5: Push default branches and verify remote refs**

Push Bridge `main` and the current maintained feature branch to the tested Bridge commit. Push Studio `master` to the tested Studio commit. Verify with `git ls-remote` and report commit hashes, test counts, EXE path, size, timestamp, and SHA-256.
