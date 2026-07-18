# Profile-aware manual product forms

Date: 2026-07-18
Status: approved direction (option 2: profile presets plus a flexible characteristics table)

## Problem

Avito Studio switches the catalog and publication configuration when the user selects a business profile, but the manual-product dialog does not receive the active profile. Its widgets, validation, and YAML output are hard-coded for Oasis air conditioners: the dialog always offers conditioner types, requires BTU, and stores `category_id` and `btu`. The Bridge manual-product loader also accepts only conditioner category IDs and is connected only to the Oasis source.

The result is misleading UI and unusable data for CARVER generators, appliances, wreaths, and baskets. A profile switch must change the product form and the data contract, not only the source YAML path.

## Goals

- Make the manual-product dialog visibly and functionally depend on the active profile.
- Preserve the current conditioner workflow and existing manual-product YAML entries.
- Provide useful preset fields for the four current profiles without preventing uncommon characteristics.
- Carry manually entered products through catalog preview and feed generation for every source.
- Keep Avito category tags profile-correct and prevent conditioner fields from leaking into other profiles.
- Clear stale catalog rows when a profile changes and adapt catalog column labels to the selected profile.

## Non-goals

- Recreate every Avito attribute for all 54 appliance groups.
- Automatically infer unknown technical characteristics from a product name.
- Publish automatically after saving a manual product.
- Change existing supplier-price import formats.

## UX direction

The interface should feel calm, task-oriented, and profile-obvious, with the restraint of Linear and Shopify Admin rather than a new visual theme. The distinctive move is a persistent active-profile banner inside the dialog: the user should never be able to mistake a CARVER form for a conditioner form.

The dialog retains the existing header, sections, spacing, photo workflow, and protected publication flow. Only the product-specific section changes.

### Common fields

Every manual product has:

- active profile (read-only banner);
- product type/group;
- brand or manufacturer;
- model/name;
- series (required only for conditioners; optional elsewhere);
- final price;
- stock quantity, default `1`;
- at least one photo;
- optional sales text/description;
- a two-column `Characteristic | Value` table with add/remove controls.

Empty characteristic rows are ignored. Duplicate non-empty names are rejected so that saving cannot silently overwrite data.

### Conditioner profile

The current `Есть НС-код` path remains available only here. The `Товара нет в базе` path contains:

- conditioner type: wall split, semi-industrial, or mobile;
- size in thousands of BTU;
- inverter compressor checkbox;
- optional area and other rows in the characteristics table.

Existing YAML fields `category_id`, `btu`, and `tech` remain compatible.

### CARVER profile

There is no Oasis/НС-code tab. The preset form contains:

- product type: generator or ATS automation;
- brand, prefilled with `CARVER` but editable;
- model/name;
- fuel type;
- voltage;
- rated power in kW;
- maximum power in kW;
- start type;
- additional characteristics table.

Recognized generator fields generate both readable description characteristics and the corresponding Avito tags (`Brand`, `Model`, `FuelType`, `Voltage`, `RatedPower`, `MaximumPower`). Empty optional tags are omitted.

### Appliances profile

There is no Oasis/НС-code tab. Product group is selected from the active profile's `profile.source_options.selected_groups`, so the form and the Avito group mapping use the same source of truth.

Selecting a group seeds empty characteristic rows without deleting values already entered by the user. Initial presets cover the examples that motivated the change:

- mixers/blenders: power, speed count, bowl/jug volume, attachments;
- refrigerators/freezers: width, height, depth, total volume, freezing capacity, color;
- washing/drying machines: load, spin speed, dimensions, color;
- default appliance groups: power, dimensions, color.

The user may add, rename, or delete rows for any product. The selected group is mapped through the existing `group_tags` configuration to `GoodsType` and `GoodsSubType`.

### Wreaths profile

There is no Oasis/НС-code tab. The preset form contains:

- product type: wreath or basket;
- name;
- shape;
- width/diameter and height;
- color palette;
- materials/composition;
- additional characteristics table.

The profile's existing feed category remains authoritative.

## Studio architecture

### Profile form schemas

A small Studio-owned schema registry, keyed by `Profile.key`, describes labels, choices, required fields, widget types, units, and mappings to stored characteristics/Avito tags. It lives separately from the dialog so the Qt layout and business definitions are independently testable. Appliance group choices are read from the active `LocalConfig`; fixed schemas do not duplicate the 54-group list.

`MainWindow` passes the active `Profile` to `AddForcedProductDialog`. The dialog builds the product-specific controls from the matching schema and shows the active-profile banner. Unknown profile keys fail closed with a clear message instead of falling back to conditioner controls.

### Catalog state

On profile switch, Studio replaces the current table model with an empty model before starting refresh. A failed CARVER/appliance refresh therefore cannot leave conditioner rows visible under the new profile.

For conditioners, catalog headers remain `Серия` and `Типоразмеры`. For per-item profiles, the primary name header becomes `Товар`, and the BTU-only column is hidden. This change is presentation-only and does not alter publication selection.

## Stored data contract

Manual products remain under `catalog.manual_products` and retain existing keys where applicable:

```yaml
catalog:
  manual_products:
    manual-ppg-1900i-0123456789:
      brand: CARVER
      title: Генератор бензиновый CARVER PPG-1900i
      series: Генераторы CARVER
      group: generator
      price: 43200
      stock: 1
      photos:
        - https://splithome.ru/static/manual-photos/manual-ppg-1900i-0123456789.jpg
      description: Компактный инверторный генератор.
      tech:
        Топливо: Бензин
        Напряжение: 220 В
        Номинальная мощность, кВт: "1.7"
        Максимальная мощность, кВт: "1.9"
      avito_tags:
        Brand: CARVER
        Model: PPG-1900i
        FuelType: Бензин
        Voltage: 220 В
        RatedPower: "1.7"
        MaximumPower: "1.9"
```

Rules:

- `title`, finite positive `price`, positive `stock`, and at least one photo are required for all profiles. `brand` is required except for the wreaths profile, where unbranded goods are valid.
- `series`, `group`, `category_id`, and `btu` are profile-dependent.
- `tech` is a display/description dictionary.
- `avito_tags` contains only category-specific XML tags and is validated as non-empty string pairs.
- Legacy conditioner entries without `group`, `description`, or `avito_tags` remain valid.
- Stable manual IDs continue to derive from normalized identity fields: saving the same identity again produces the same ID. Changing brand/model/series is an identity change and remains outside this add-only dialog.

## Bridge architecture and data flow

1. The selected profile YAML is loaded.
2. The configured supplier source produces its normal offers.
3. A generalized manual-product loader converts `catalog.manual_products` to `Offer` objects for that profile.
4. Supplier and manual offers are combined before grouping, catalog export, pricing, and feed generation.
5. Manual products remain `forced=True`, so they bypass the publication whitelist but still require a photo and a positive final price.
6. `tech` becomes readable offer attributes; `avito_tags` becomes `avito_tag:<TagName>` attributes consumed by the existing generic feed builder.
7. Appliance `group` adds the existing `group_tags` mapping. Explicit validated tags take precedence only for their exact tag name.
8. For profiles using `content.description_attr: desc_long`, Bridge builds `desc_long` deterministically from title, optional description, and technical rows. Conditioner profiles continue through the existing conditioner renderer.

The generalized loader is called from one shared profile-offer entry point used by both the production cycle and `catalog_export`. Oasis no longer appends manual products separately, preventing duplicates.

## Validation and errors

- The save button is enabled only when the active schema's required fields, price, stock, and photo are present.
- Numeric fields reject zero and negative values; optional numeric fields may be empty.
- Duplicate characteristic names and unsafe manual IDs produce user-facing validation messages.
- Missing or malformed profile schema never falls back to another business profile.
- Photo upload remains first; YAML is changed only after a successful upload.
- Publication remains a separate confirmed action.
- A source refresh error shows an empty catalog for the active profile, never stale rows from the previous profile.

## Testing

Studio tests will prove:

- `MainWindow` passes the active profile to the dialog;
- the НС-code tab is present only for conditioners;
- each profile exposes its expected fields and never exposes BTU/inverter fields from another profile;
- appliance group selection seeds suitable rows without destroying user-entered characteristics;
- validation follows the active schema;
- saved YAML contains the expected common, technical, and Avito-tag data;
- switching profiles clears stale rows and applies the correct catalog headers.

Bridge tests will prove:

- legacy conditioner manual entries still load;
- generic CARVER, appliance, and wreath entries load without BTU/category IDs;
- manual offers are appended exactly once for every source;
- appliance group tags and explicit CARVER Avito tags reach the generated XML;
- non-conditioner manual descriptions contain the entered characteristics;
- invalid profile-specific data fails with an actionable path in the error.

Final verification includes both complete test suites, a rebuilt PyInstaller executable, and a GUI smoke check opening the manual-product dialog under all four profiles.

## Delivery

Implementation is complete only when:

- both repositories' tests pass after the final edit;
- the new executable is rebuilt and starts successfully;
- the four profile forms are visually inspected;
- Studio and Bridge changes are committed and pushed to their GitHub default branches without including unrelated local files.
