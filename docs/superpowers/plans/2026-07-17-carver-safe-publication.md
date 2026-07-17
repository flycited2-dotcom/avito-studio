# CARVER Safe Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and safely publish a one-item CARVER XML feed from the supplied XLSX with a 7% markup rounded up to 10 rubles.

**Architecture:** `avito-bridge` owns price calculation, XLSX parsing, profile data, and the XML contract. `avito-studio` owns selecting and validating the local price file, saving the per-machine path, building the local feed, and atomically replacing the public VPS file. The first live feed contains only `PPG-1900IS`; ATS products remain disabled.

**Tech Stack:** Python 3.11+, PySide6, ruamel.yaml, openpyxl, pytest, pytest-qt, SSH, Avito XML Autoload.

## Global Constraints

- Markup is exactly 7 percent before rounding.
- Final price is rounded upward to the nearest 10 rubles.
- Source workbook is copied, never edited in place.
- The Git-tracked profile never contains a machine-specific absolute path.
- The public file is `/opt/oasis/staticfiles/avito-feed-carver.xml`.
- The public file is replaced only after local and server-side XML validation.
- The first feed contains only `PPG-1900IS`; ATS products remain excluded.
- Category candidate is `Category=Ремонт и строительство`, `GoodsType=Инструменты`, `GoodsSubType=Генераторы` and must be confirmed by Avito's validator or item report.

---

### Task 1: Implement the advertised rounding modes

**Files:**
- Modify: `avito-bridge/src/avito_bridge/pricing/pricing.py`
- Modify: `avito-bridge/tests/test_pricing.py`

**Interfaces:**
- Produces: `round_up(raw: float, step: int) -> int`
- Preserves: `round_up_90(raw: float) -> int`
- Changes: `compute_price(offer, cfg)` dispatches `none`, `up_to_10`, `up_to_90`, and `up_to_100` separately.

- [ ] **Step 1: Write failing price tests**

```python
def test_carver_markup_rounds_up_to_10():
    cfg = PricingConfig(default_markup_pct=7, min_margin_abs=0,
                        rounding="up_to_10", rules=[])
    result = compute_price(_offer(Decimal("22786"), source="carver_xlsx"), cfg)
    assert result.price == 24390


def test_round_up_to_100_is_not_up_to_90():
    cfg = PricingConfig(default_markup_pct=0, min_margin_abs=0,
                        rounding="up_to_100", rules=[])
    assert compute_price(_offer(Decimal("12491")), cfg).price == 12500
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_pricing.py -q`

Expected: the CARVER case returns a value ending in `90` through the old fallback and at least one new assertion fails.

- [ ] **Step 3: Implement minimal dispatch**

```python
import math


def round_up(raw: float, step: int) -> int:
    return int(math.ceil(raw / step) * step)


def _rounded_price(raw: float, mode: str) -> int:
    if mode == "none":
        return int(raw)
    if mode == "up_to_10":
        return round_up(raw, 10)
    if mode == "up_to_100":
        return round_up(raw, 100)
    if mode == "up_to_90":
        return round_up_90(raw)
    raise ValueError(f"Неизвестный режим округления: {mode}")
```

Use `_rounded_price(raw, cfg.rounding)` from `compute_price`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_pricing.py -q`

Expected: all pricing tests pass and `PPG-1900IS` resolves to `24390`.

- [ ] **Step 5: Commit bridge change**

```powershell
git add src/avito_bridge/pricing/pricing.py tests/test_pricing.py
git commit -m "fix: implement CARVER price rounding modes"
```

---

### Task 2: Make the CARVER profile safe and portable

**Files:**
- Modify: `avito-bridge/.gitignore`
- Modify: `avito-bridge/profiles/carver.yaml`
- Modify: `avito-bridge/src/avito_bridge/config.py`
- Modify: `avito-bridge/tests/test_config.py`

**Interfaces:**
- Produces: `AppConfig.public_feed_path: str`
- Profile values: empty local `source_options.path`, public feed path, 7% markup, `up_to_10`, category candidate, and disabled whitelist.

- [ ] **Step 1: Write failing config test**

```python
def test_carver_profile_has_safe_publication_defaults():
    cfg = load_config(PROJECT_ROOT / "profiles" / "carver.yaml")
    assert cfg.source_options["path"] == ""
    assert cfg.pricing.default_markup_pct == 7
    assert cfg.pricing.rounding == "up_to_10"
    assert cfg.public_feed_path == "/opt/oasis/staticfiles/avito-feed-carver.xml"
    assert cfg.feed.base_tags["GoodsSubType"] == "Генераторы"
    assert cfg.selected_series == frozenset({"__none__"})
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_config.py -q`

Expected: `AppConfig` has no `public_feed_path` and the profile still contains the old TLT-1 path.

- [ ] **Step 3: Add configuration field and profile values**

Add to `AppConfig`:

```python
public_feed_path: str = ""
```

Load it from `profile.public_feed_path`. Update `profiles/carver.yaml`:

```yaml
profile:
  source_options:
    path: ""
  public_feed_path: "/opt/oasis/staticfiles/avito-feed-carver.xml"

pricing:
  rounding: up_to_10
  default_markup_pct: 7
  price_confirmed: false

feed:
  base_tags:
    AdType: "Товар приобретен на продажу"
    Condition: "Новое"
    Category: "Ремонт и строительство"
    GoodsType: "Инструменты"
    GoodsSubType: "Генераторы"
```

Add `/runtime/` to `.gitignore`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_config.py tests/test_carver_xlsx.py tests/test_pricing.py -q`

Expected: all selected bridge tests pass.

- [ ] **Step 5: Commit bridge change**

```powershell
git add .gitignore profiles/carver.yaml src/avito_bridge/config.py tests/test_config.py
git commit -m "feat: configure safe CARVER publication defaults"
```

---

### Task 3: Import and validate the price file in Studio

**Files:**
- Create: `avito-studio/src/avito_studio/carver_price_file.py`
- Create: `avito-studio/tests/test_carver_price_file.py`
- Modify: `avito-studio/src/avito_studio/local_config.py`
- Modify: `avito-studio/src/avito_studio/carver_publish_settings_dialog.py`
- Modify: `avito-studio/tests/test_carver_publish_settings.py`

**Interfaces:**
- Produces: `import_carver_price(source: Path, bridge_root: Path) -> tuple[Path, int]`
- Produces: `LocalConfig.get_source_path() -> str`
- Produces: `LocalConfig.set_source_path(path: Path) -> None`
- Dialog stores `GoodsSubType` as well as Category and GoodsType.

- [ ] **Step 1: Write failing import tests**

```python
def test_valid_price_is_copied_only_after_validation(tmp_path, monkeypatch):
    source = tmp_path / "price.xlsx"
    source.write_bytes(b"xlsx")
    monkeypatch.setattr(price_file, "parse_carver_xlsx",
                        lambda path: [{"article": str(i)} for i in range(23)])
    monkeypatch.setattr(price_file, "extract_embedded_photos",
                        lambda path: {str(i): b"photo" for i in range(23)})

    target, count = price_file.import_carver_price(source, tmp_path / "bridge")

    assert target == tmp_path / "bridge" / "runtime" / "carver" / "current.xlsx"
    assert target.read_bytes() == b"xlsx"
    assert count == 23


def test_invalid_price_does_not_replace_current(tmp_path, monkeypatch):
    current = tmp_path / "bridge" / "runtime" / "carver" / "current.xlsx"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"last-good")
    source = tmp_path / "bad.xlsx"
    source.write_bytes(b"bad")
    monkeypatch.setattr(price_file, "parse_carver_xlsx", lambda path: [])

    with pytest.raises(ValueError, match="товарных позиций"):
        price_file.import_carver_price(source, tmp_path / "bridge")

    assert current.read_bytes() == b"last-good"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_carver_price_file.py -q`

Expected: import fails because `carver_price_file` does not exist.

- [ ] **Step 3: Implement validated atomic copy**

```python
def import_carver_price(source: Path, bridge_root: Path) -> tuple[Path, int]:
    rows = parse_carver_xlsx(source)
    photos = extract_embedded_photos(source)
    if len(rows) != 23:
        raise ValueError(f"Ожидалось 23 товарных позиции, найдено {len(rows)}.")
    missing = [row["article"] for row in rows if row["article"] not in photos]
    if missing:
        raise ValueError("Нет встроенных фото: " + ", ".join(missing[:5]))
    target = Path(bridge_root) / "runtime" / "carver" / "current.xlsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".xlsx.tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(target)
    return target.resolve(), len(rows)
```

Add source path getters/setters to `LocalConfig`. Extend the settings dialog with a read-only path field and `Выбрать Excel` button using the existing themed file picker; save the imported absolute path, `GoodsSubType`, 7%, and `up_to_10`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_carver_price_file.py tests/test_carver_publish_settings.py -q`

Expected: all import and settings tests pass.

- [ ] **Step 5: Commit Studio change**

```powershell
git add src/avito_studio/carver_price_file.py src/avito_studio/local_config.py src/avito_studio/carver_publish_settings_dialog.py tests/test_carver_price_file.py tests/test_carver_publish_settings.py
git commit -m "feat: import portable CARVER price files"
```

---

### Task 4: Validate and atomically publish the public XML

**Files:**
- Modify: `avito-studio/src/avito_studio/deploy.py`
- Modify: `avito-studio/tests/test_deploy.py`

**Interfaces:**
- Produces: `validate_feed_xml(data: bytes, expected_ads: int) -> None`
- Changes: `deploy_local_feed(config_path, ssh)` uploads to a hidden temporary public path and runs server validation before atomic `mv`.

- [ ] **Step 1: Write failing deployment tests**

```python
def test_deploy_local_feed_uses_validated_atomic_public_path(...):
    out = deploy_local_feed(cfg, ssh)
    remote_path, data = ssh.put_calls[0]
    assert remote_path == "/opt/oasis/staticfiles/.avito-feed-carver.xml.tmp"
    assert "xml.etree.ElementTree" in ssh.run_calls[0]
    assert "&& mv -f" in ssh.run_calls[0]
    assert "/opt/oasis/staticfiles/avito-feed-carver.xml" in ssh.run_calls[0]
    assert "ads_built=1" in out


def test_validate_feed_rejects_zero_ads():
    with pytest.raises(ValueError, match="объявлен"):
        validate_feed_xml(b"<Ads></Ads>", expected_ads=1)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_deploy.py -q`

Expected: upload still targets `/opt/avito-bridge/feed_out/carver.xml` and `validate_feed_xml` is missing.

- [ ] **Step 3: Implement validation and atomic command**

Parse XML locally with `xml.etree.ElementTree`, verify root `Ads`, count `<Ad>`, and required fields `Id`, `Title`, `Description`, `Price`, and `Images/Image`. Validate `cfg.public_feed_path` is an absolute path below `/opt/oasis/staticfiles/`. Upload to `.<basename>.tmp`. Run remote Python XML parsing followed by `&& mv -f temporary final`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_deploy.py -q`

Expected: deployment tests pass; no test uploads directly to the final path.

- [ ] **Step 5: Commit Studio change**

```powershell
git add src/avito_studio/deploy.py tests/test_deploy.py
git commit -m "feat: atomically publish validated CARVER feeds"
```

---

### Task 5: Full regression and real-price dry run

**Files:**
- Runtime only: `avito-bridge/runtime/carver/current.xlsx`
- Runtime only: local edits in `avito-bridge/profiles/carver.yaml`
- Output: temporary local `carver.xml` for verification; do not commit the generated feed.

**Interfaces:**
- Consumes: supplied workbook, CARVER profile, parsing, pricing, rendering, and selection.
- Produces: one locally verified `PPG-1900IS` ad priced at 24,390 rubles.

- [ ] **Step 1: Run both complete suites**

Run Studio: `python -m pytest tests -q`

Expected: at least 134 tests pass plus new Studio tests.

Run Bridge: `python -m pytest tests -q`

Expected: at least 167 tests pass plus new Bridge tests.

- [ ] **Step 2: Import the supplied XLSX through the new helper**

Run a Python one-liner that calls `import_carver_price` with
`C:\Users\user\Downloads\Прайс_генераторы_CARVER_фото_15.07.xlsx` and the bridge worktree.

Expected: `23` positions and `runtime/carver/current.xlsx` exists.

- [ ] **Step 3: Prepare local canary configuration**

Set the source path to the imported absolute path, keep category candidate values,
store 7% plus `up_to_10`, upload the `PPG-1900IS` embedded image through the existing
manual-photo function, and select only key `carver_xlsx|item|carver:PPG-1900IS`.

- [ ] **Step 4: Build the local canary XML without SSH**

Run the same `get_source` plus `run_cycle` path used by `deploy_local_feed` into a temporary directory.

Expected assertions:

```text
source offers parsed=23
offers_in=1 after the one-item whitelist
ads_built=1
PPG-1900IS present
Price=24390
exactly one Ad
at least one Image
no ATS-* identifiers
```

- [ ] **Step 5: Inspect XML and retain no generated repository artifacts**

Run XML parsing assertions and `git status --short` in both worktrees.

Expected: only intentional code/config commits; `runtime/` and generated feeds are ignored.

---

### Task 6: Controlled public canary

**Files:**
- No source changes expected.
- External target: `/opt/oasis/staticfiles/avito-feed-carver.xml`.

**Interfaces:**
- Consumes: verified one-ad XML and existing SSH client.
- Produces: HTTP 200 public one-ad feed, followed by Avito upload/report evidence.

- [ ] **Step 1: Publish with `deploy_local_feed`**

Expected: upload goes to hidden temporary path, server XML validation succeeds, atomic move completes.

- [ ] **Step 2: Verify public URL**

GET `https://splithome.ru/static/avito-feed-carver.xml`.

Expected: HTTP 200, exactly one `<Ad>`, `PPG-1900IS`, price 24,390, and an image URL returning HTTP 200.

- [ ] **Step 3: Connect or trigger the correct Avito Autoload account**

Use the account already associated with CARVER/default product publishing. If repository and environment configuration cannot identify the account unambiguously, stop before the external write and report the exact missing account selection.

- [ ] **Step 4: Read the final item report**

Expected: `PPG-1900IS` is `active`. If category is rejected, keep the one-item canary and adjust only category tags from the official report.

- [ ] **Step 5: Merge only after the canary is accepted**

Merge/publish order: `avito-bridge` first, `avito-studio` second. Build the Windows executable only after both merged heads pass their full suites.
