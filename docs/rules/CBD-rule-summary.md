# CBD Item Code Rules — extracted & verified 2026-07-23

Source: `CBD.tmp.xlsx` — rule image embedded in sheet "Rule", verified against 22,587 items in sheet "All item CBD".

## Pattern 1 — Spare parts (Stock): 12 digits

`ComCode(2) + ItemGroup(2) + ItemCategory(2) + SubCategory(2) + Running(4)`

Example: `990501010001` = 99 (Inter com) + 05 (SP) + 01 (SM Mechanical) + 01 (Bearing) + 0001

| Segment | Values (from rule doc) |
|---|---|
| Company code | CBD=11, APG=12, ACM=13, APM=14, Inter com=99 |
| Item Group | ของใช้=01, PK=02, RM=03, FG=04, SP=05 |
| Item Category | SM Mechanical=01, SP Pneumatic=02, SE Electrical=03, SC Consumable=04, ST Tools=05, SMO Motor/Pump/Gear=06 |
| Sub Category | per-category list (1.1 Bearing, 1.2 O-ring/Seal/Gasket, 1.3 Bolt & nut, 1.4 Chain & Conveyor, 1.5 Spring and bush, 1.6 Misc, 2.1 Cylinder, 2.2 Actuator and valve, 2.3 Tube and piping, 2.4 Solenoid, 2.5 Misc, 3.1 Sensor, 3.2 Breaker, 3.3 Electrical module & board, 3.4 Encoder, 3.5 Inverter, 3.6 Power supply, 3.7 Cable & Connector, 3.8 Others Electrical, 4.1 Filter, 4.2 Lubricant, 4.3 Misc, 6.1 Motor, 6.2 Water pump, 6.3 Gear) |
| Running | 4 digits, per Category+SubCategory group |

Observed: all existing stock items use prefix `9905` (Inter com + SP group). 29 distinct 8-digit prefixes in data.

## Pattern 2 — Non-Spare parts

`64 + Category(2 letters) + Running(6)` — `64` is a fixed version prefix (พ.ศ. 2564 เริ่มใช้, does NOT change by year).

Special case: `SVSP` uses digits 3–6 as category + Running(4), e.g. `64SVSP0313`.

Categories (rule doc): SV, SVSP, FQ, MD, CS, IT, OF, SF, BD, WF, MC, FL, LQ.
**Also found in real data but NOT in rule doc: CH, FU, MS, OT, TR, VE, SP** → category table must be editable config in the new system.

## Item naming convention

`ชื่อสินค้า / แบรนด์ / รุ่น / ขนาด / ชนิด / สี / Item ตามเจ้าของเครื่องจักร`
e.g. `Ball Bearing SKF UCF209-28 Size:1-3/4" 44.45mm`

## Findings that constrain system design

1. **Next running number = max(existing)+1, never count-based.** Many groups have gaps (99050101: 620 items but max running 2297; 64IT: 650 items but max 6613).
2. This export may not be the complete master (unusually large gaps) → at go-live, sync numbers from a complete source (AX DB or full export).
3. ~5,500 items use ~20 legacy code shapes (CA3003, AD-1000, BN1-001, MIXBOT0001, 64SVSP0001, …). New system never generates these but MUST include them in duplicate search.
4. Legacy data quality: mixed Thai/English names, inconsistent spacing (e.g. leading spaces in `  Gluer-0256350330`) → duplicate check needs normalization + fuzzy matching, not exact match.

## Open questions

- Mapping of the 11 factories → which code pattern each uses (answered "แบ่งแบบอื่น" — details pending).
- D365 rules (APM, APG, ACM): files `Running Items Dynamics 365 *.xlsx` are IRM-encrypted, cannot be read — need unprotected copies.
- Does non-stock running continue from max per category forever, or ever reset?
