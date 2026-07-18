# Universal Bulk Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в Avito Studio безопасное массовое включение/отключение и изменение текущих цен для любого профиля, затем выполнить утверждённую операцию с кондиционерами.

**Architecture:** `avito-bridge` экспортирует по каждой модели итоговую и закупочную цену. Avito Studio строит чистый предварительный план изменений, показывает его в универсальном диалоге и только после локального подтверждения одним сохранением записывает YAML-переопределения. Публикация остаётся отдельной существующей командой.

**Tech Stack:** Python 3.11+, PySide6, ruamel.yaml, pytest, pytest-qt, PyInstaller.

## Global Constraints

- Одна операция работает только с текущим профилем.
- Расчёт выполняется от текущей итоговой цены каждой модели и применяется один раз.
- Цена по умолчанию не опускается ниже закупочной.
- Массовое действие ничего не отправляет на сервер или Avito.
- Исходные значения не перезаписываются; используются существующие YAML overrides.
- `tests/test_pricing.py` уже существует как посторонний untracked-файл и не включается в коммиты без отдельной проверки владельца.

---

### Task 1: Экспорт закупочной цены модели

**Files:**
- Modify: `../avito-bridge/src/avito_bridge/catalog_export.py`
- Test: `../avito-bridge/tests/test_catalog_export.py`

**Interfaces:**
- Produces: JSON member fields `cost: int | null`, `price: int | null`, `price_ok: bool`.

- [ ] **Step 1: Write the failing test**

Добавить проверку в `test_catalog_export.py`, что член с `Offer(cost=Decimal("10000"))` экспортирует `cost == 10000`, а предложение без закупочной цены экспортирует `cost is None`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_catalog_export.py -q`

Expected: FAIL по отсутствующему ключу `cost`.

- [ ] **Step 3: Write minimal implementation**

В `_member_json` добавить:

```python
cost = int(m.cost) if m.cost is not None else None
return {
    "nc_code": nc,
    "btu_calc": m.btu_calc,
    "stock": m.stock,
    "cost": cost,
    "price": pr.price,
    "price_ok": pr.ok,
    "forced": m.forced,
}
```

- [ ] **Step 4: Run tests and commit**

Run: `pytest tests/test_catalog_export.py tests/test_pricing.py -q`

Expected: PASS.

Commit only the two bridge files with message `feat: expose catalog member costs`.

### Task 2: Сохранить все модели серии в Studio

**Files:**
- Modify: `src/avito_studio/catalog_service.py`
- Modify: `tests/test_catalog_service.py`
- Modify: `tests/test_main_window.py`

**Interfaces:**
- Produces: `CatalogMember(nc_code: str, current_price: int | None, cost: int | None, price_ok: bool, forced: bool)`.
- Produces: `CatalogRow.members: tuple[CatalogMember, ...]` with an empty default for existing tests.

- [ ] **Step 1: Write the failing catalog test**

Расширить `FAKE_JSON` полями `cost` и проверить:

```python
assert sensei.members == (
    CatalogMember("НС-1", 25990, 24000, True, False),
    CatalogMember("НС-2", 27990, 26000, True, False),
)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_catalog_service.py -q`

Expected: FAIL при импорте отсутствующего `CatalogMember`.

- [ ] **Step 3: Add the immutable member model**

```python
@dataclass(frozen=True)
class CatalogMember:
    nc_code: str
    current_price: int | None
    cost: int | None
    price_ok: bool
    forced: bool
```

Добавить в `CatalogRow` поле `members: tuple[CatalogMember, ...] = ()` и в `_rows_from_data` преобразовать каждый JSON member, нормализуя отсутствующий `cost` в `None` для обратной совместимости.

- [ ] **Step 4: Update direct CatalogRow fixtures**

Существующие конструкторы не менять: пустой default обязан сохранить совместимость. В `FakeSsh` добавить `cost`, чтобы интеграционные тесты проверяли новый контракт.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_catalog_service.py tests/test_main_window.py -q`

Expected: PASS.

Commit with message `feat: retain catalog member prices`.

### Task 3: Чистый расчёт массового изменения

**Files:**
- Create: `src/avito_studio/bulk_changes.py`
- Create: `tests/test_bulk_changes.py`

**Interfaces:**
- Produces: `BulkRequest`, `MemberPriceChange`, `SeriesChange`, `BulkPreview`.
- Produces: `build_bulk_preview(rows: list[CatalogRow], request: BulkRequest) -> BulkPreview`.

- [ ] **Step 1: Write failing tests for selection and price rules**

Покрыть следующие случаи отдельными тестами:

```python
request = BulkRequest(
    target_keys=("a", "b"),
    publication=None,
    price_mode="percent",
    price_value=Decimal("-5"),
)
preview = build_bulk_preview(rows, request)
assert [(c.nc_code, c.old_price, c.new_price) for c in preview.price_changes] == [
    ("A-1", 20000, 19000),
]
assert preview.skipped_below_cost == ("B-1",)
```

Также проверить режимы `amount`, `fixed`, `reset`, пустой выбор, неизвестный key, некорректный процент `-100`, модель без цены и изменение публикации без цены.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bulk_changes.py -q`

Expected: FAIL с `ModuleNotFoundError`.

- [ ] **Step 3: Implement value objects**

Использовать frozen dataclasses и точные литералы:

```python
PriceMode = Literal["unchanged", "percent", "amount", "fixed", "reset"]

@dataclass(frozen=True)
class BulkRequest:
    target_keys: tuple[str, ...]
    publication: bool | None = None
    price_mode: PriceMode = "unchanged"
    price_value: Decimal | None = None
```

`MemberPriceChange` хранит `nc_code`, `old_price`, `new_price`, `forced`; `SeriesChange` — key и старое/новое состояние; `BulkPreview` — изменения, неизвестные ключи, пропуски без цены и ниже закупки.

- [ ] **Step 4: Implement deterministic pricing**

Процент и сумма используют `Decimal`; результат округляется до целого `ROUND_HALF_UP`. Для `percent` допустим диапазон `(-100, 10000]`. Для `fixed` требуется положительное значение. Если рассчитанная цена ниже известного `cost`, модель попадает в `skipped_below_cost`. `reset` создаёт изменение с `new_price=None`.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_bulk_changes.py -q`

Expected: PASS.

Commit with message `feat: calculate bulk catalog changes`.

### Task 4: Атомарно применить предварительный план

**Files:**
- Modify: `src/avito_studio/bulk_changes.py`
- Modify: `src/avito_studio/local_config.py`
- Modify: `tests/test_bulk_changes.py`
- Modify: `tests/test_local_config.py`

**Interfaces:**
- Produces: `apply_bulk_preview(local_cfg: LocalConfig, preview: BulkPreview) -> None`.
- Produces: `LocalConfig.has_force_include(nc_code: str) -> bool`.

- [ ] **Step 1: Write failing application tests**

Проверить одним reload YAML, что обычная модель записана в `manual_price_override`, forced-модель меняет `force_include.price`, `reset` удаляет обычный override, публикация меняет `selected_series`, а `save()` вызывается один раз после всех изменений.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bulk_changes.py tests/test_local_config.py -q`

Expected: FAIL по отсутствующим функциям.

- [ ] **Step 3: Implement local mutations**

`apply_bulk_preview` сначала проверяет, что preview не содержит неизвестных ключей и имеет хотя бы одно изменение. Затем применяет публикацию, forced-цены через `set_force_price`, обычные цены через `set_manual_price`, reset через `remove_manual_price`, и вызывает `local_cfg.save()` ровно один раз.

Forced-модель нельзя сбросить к авто, потому что её цена является обязательной частью `force_include`; она попадает в явный список пропусков preview.

- [ ] **Step 4: Run tests and commit**

Run: `pytest tests/test_bulk_changes.py tests/test_local_config.py -q`

Expected: PASS.

Commit with message `feat: apply bulk changes atomically`.

### Task 5: Универсальный диалог массового редактора

**Files:**
- Create: `src/avito_studio/bulk_edit_dialog.py`
- Create: `tests/test_bulk_edit_dialog.py`

**Interfaces:**
- Consumes: `build_bulk_preview` and `apply_bulk_preview`.
- Produces: `BulkEditDialog(rows, local_cfg, parent=None)` with `applied = Signal(BulkPreview)`.

- [ ] **Step 1: Write failing UI tests**

С помощью `pytest-qt` проверить:

- диалог показывает только строки текущего `rows`;
- фильтр и «Выбрать найденные» фиксируют нужные keys;
- публикацию можно оставить без изменений, включить или выключить;
- процент `-5` показывает старые и новые цены всех моделей;
- пропуск ниже закупки виден до сохранения;
- кнопка применения выключена при пустом выборе или ошибочном значении;
- подтверждение вызывает `apply_bulk_preview`, отклонение не меняет YAML.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bulk_edit_dialog.py -q`

Expected: FAIL с `ModuleNotFoundError`.

- [ ] **Step 3: Build the dialog in existing UI style**

Использовать `dialog_header`, `FormSection`, `dialog_footer` и `role_button`. Диалог содержит поиск, таблицу с чекбоксом выбора, бренд, товар/серию, публикацию и диапазон цен; комбобокс публикации; комбобокс режима цены; числовое значение; таблицу preview; счётчики изменений и пропусков; «Отмена» и «Применить локально».

Изменение любого контрола пересобирает preview. Перед применением показать `QMessageBox.question` с количеством серий и модельных цен. Это подтверждение локальной массовой операции, не публикация.

- [ ] **Step 4: Make the dialog keyboard-accessible**

Задать понятные accessible names, tab order и shortcut `Ctrl+Shift+B` на действие главного окна. Кнопка применения становится default только при валидном preview.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_bulk_edit_dialog.py tests/test_ui_style_contract.py -q`

Expected: PASS.

Commit with message `feat: add universal bulk editor dialog`.

### Task 6: Интеграция с каталогом

**Files:**
- Modify: `src/avito_studio/main_window.py`
- Modify: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `BulkEditDialog.applied`.
- Produces: toolbar action `Массовое изменение` visible for every profile.

- [ ] **Step 1: Write failing integration tests**

Проверить, что действие видимо для conditioners, wreaths, appliances и carver; shortcut зарегистрирован; успешный dialog обновляет модель и dashboard; отмена не меняет конфигурацию; действие выключается во время refresh/deploy.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_window.py -q`

Expected: FAIL по отсутствующему action.

- [ ] **Step 3: Add and wire the action**

Создать QAction `Массовое изменение`, добавить `QKeySequence("Ctrl+Shift+B")`, включить в catalog toolbar и `_busy_actions`. `_open_bulk_edit_dialog` передаёт `self.model.rows` и `self.local_cfg`; после `applied` обновляет `row.selected`, price labels из preview, dashboard и status bar без сетевой публикации.

- [ ] **Step 4: Run tests and commit**

Run: `pytest tests/test_main_window.py tests/test_catalog_table_model.py -q`

Expected: PASS.

Commit with message `feat: wire bulk editor into catalog`.

### Task 7: Полная проверка и Windows-сборка

**Files:**
- Verify: both repositories
- Build output: `dist/AvitoContentStudio.exe`

- [ ] **Step 1: Run bridge tests**

Run in `avito-bridge`: `pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Run Studio tests**

Run in `avito-studio`: `pytest -q`

Expected: all tests pass; pre-existing unrelated `tests/test_pricing.py` is reported separately if it is not part of tracked suite.

- [ ] **Step 3: Build the application**

Run: `pyinstaller --noconfirm avito_studio.spec`

Expected: exit code 0 and `dist/AvitoContentStudio.exe` exists.

- [ ] **Step 4: Exercise the real UI without publishing**

Запустить новую сборку. В профиле кондиционеров открыть массовый редактор, выбрать `XIGMA JETPRO` и `Ballu Aura`, выключить публикацию и применить локально. Второй операцией выбрать все остальные публикуемые кондиционеры, задать `-5%`, проверить список моделей, ограничения по закупке и применить локально.

- [ ] **Step 5: Verify persisted result**

Обновить каталог и подтвердить: обе серии выключены; выбранных серий стало на две меньше; итоговые цены каждой затронутой модели равны округлённым `old * 0.95`; товары ниже закупочной не изменены и перечислены.

- [ ] **Step 6: Stop at the publication confirmation**

Открыть существующую сводку «Опубликовать изменения», зафиксировать её содержание и остановиться до ответа пользователя. Только после отдельного подтверждения нажать финальное «Да» и проверить успешную пересборку фида.

- [ ] **Step 7: Commit and push implementation**

Проверить `git diff --check`, `git status -sb` и точный staged diff в каждом репозитории. Не включать посторонние локальные изменения. Push выполняется только после успешных тестов соответствующей ветки.
