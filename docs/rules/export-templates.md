# AX/D365 Import Templates — analysis (2026-07-27)

Source: `Up load Item Temp/Temp Up Load Item - {CBD,APM,APG,ACM}.xlsx`.
Each factory has a distinct import format. Export module fills the **variable**
fields per item and keeps the rest as **fixed per-factory constants** taken from
the temp files.

## Sheet structure per factory

| Factory | Sheets |
|---|---|
| CBD | `CBD_ReleasedProduct_Template_RE` (21 col) + `CBG_ItemWMSsetupEntity` |
| APM | `Products_V2`, `Released_products_V2`, `Product_category_assignments`, `Default_order_settings`, `CBG_ItemWMSsetupEntity` |
| APG | same 5 sheets as APM |
| ACM | `ACM - Item Update` (55 col) + `ACM Purecument Category` + `CBG_ItemWMSsetupEntity` |

CBD header is on row 2 (row 1 is Thai instruction hints); data from row 3.
Others: header row 1, data from row 2.

## Variable fields (change per item) — confirmed by diffing temp rows

| Field | CBD | APM/APG | ACM | Source in our system |
|---|---|---|---|---|
| Item code | ItemId / DisplayProductNumber | PRODUCTNUMBER / ITEMNUMBER | ItemId / DisplayProductNumber | generated_code |
| Name | EcoResProductTranslation_Name / NameAlias | PRODUCTNAME / PRODUCTDESCRIPTION | EcoResProductTranslation_Name / NameAlias | request.item_name (composed) |
| Search name | SearchName | PRODUCTSEARCHNAME / SEARCHNAME | SearchName | short name — **NEW field needed** |
| Product type | Item (fixed here) | Service (this batch) | Item / SERVICE | from code system (Service vs Item) |
| UOM | Pcs / Set | Job (service) | JOB / PC / Set | request.uom (dropdown) |
| Item group id | SPT / TES | EN-FS (ProductGroup, fixed) | SERVICE (fixed) | **mapping หมวด→group, config** |
| Model group id | FIFO_S_NQL / FIFO_S_NQ | EN (fixed) | (fixed cols) | **mapping, config** |
| Procurement category | (not in CBD sheet) | 54050102 … | 54080601 … | request.procurement_category (dropdown) |
| Purchase price | — | PURCHASEPRICE | InventTableModulePurch_Price | optional, procurement fills |

Everything else observed identical within each file → treat as fixed per-factory
constants (EN-US, GOODS, No Batch, SWL, site=APM/APG, warehouse=SPP for APG, Yes/Yes, etc.).

## Reference lists still needed from Peter (editable config, seed with observed)

1. **UOM list** — observed: Pcs, Set, PC, Job. Need full AX-valid list.
2. **Procurement Category list** — observed only 3 (54050102 Computer expenses,
   54080401 MA-Outsource Maintenance, 54080601 MA-Overhaul). Need full list per
   factory/hierarchy.
3. **Group → (ItemGroupId, ModelGroupId) mapping** — observed CBD uses SPT vs TES
   and FIFO_S_NQL vs FIFO_S_NQ depending on หมวด/ชนิด; need the rule.

Decision (per discovery answers 2026-07-27): all three are editable config tables,
seeded with observed values, completed by Peter in the admin UI before go-live —
same non-blocking pattern as code_groups.

## Fields to add to item_requests for export
- search_name (short name; default = item_name truncated, editable)
- procurement_category (FK to config)
- purchase_price (nullable)
- item_group_id / model_group_id: resolved at export time from mapping, overridable
