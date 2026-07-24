# D365 Item Code Rules (APM, APG, ACM) — extracted 2026-07-23

Source: Google Drive sheets "Stock (APM,APG,ACM)", "Non-Stoock (APM,APG,ACM)", "Service (APM,APG,ACM)".

## Common structure: 11 digits

`ItemGroup(3) + 0000 + Running(4)` — running starts at 0001 per group.

## Stock (Item groups 800–806)

| Group | Name | Scope |
|---|---|---|
| 800 | Spare part / Mechanic Part | อะไหล่สำรองเครื่องจักร/อุปกรณ์ |
| 801 | Oil | น้ำมันหล่อลื่น เกียร์ ไฮดรอลิค ฯลฯ |
| 802 | Plate | แม่พิมพ์เครื่องพิมพ์กราเวีย/เฟล็กโซ่ |
| 803 | Chemical | เคมีภัณฑ์โรงงาน/ทำความสะอาด, แก๊ส |
| 804 | Tooling | เครื่องมือและอุปกรณ์ช่าง |
| 805 | Consume | วัสดุสิ้นเปลืองโรงงาน/สำนักงาน |
| 806 | Mould | **โครงสร้างพิเศษ:** `806 + MouldType(3) + Running(5)` เช่น `80600100001` = AP-01 150 ml. CARABAO — mould type เป็น running ของชนิดขวด (001, 002, …015 ณ วันที่ดึงข้อมูล) |

## Non-Stock (Item groups 900–908)

| Group | Name | Scope owner |
|---|---|---|
| 900 | Spare Parts & Mechanical Parts | SPT |
| 901 | Electrical Parts | SPT |
| 902 | Lab Instruments | SPT |
| 903 | Chemicals (Oil & Gas) | SPT |
| 904 | Construction Materials | SPT |
| 905 | Factory Consume | SPT |
| 906 | General Consume | GN |
| 907 | IT Hardware & Accessories | GN |
| 908 | Marketing | GN |

## Service (Item groups 700–710)

| Group | Name | Scope owner |
|---|---|---|
| 700 | Installation & Repair Machinery | SPT |
| 701 | Construction & Civil & Utility | SPT |
| 702 | Calibration & Certification Service | SPT |
| 703 | Tools & Electrical Equip. Service | SPT |
| 704 | Safety & Environmental Service | SPT |
| 705 | Rental | SPT |
| 706 | Marketing Service | GN |
| 707 | IT Software & Service | GN |
| 708 | Generals Service | GN |
| 709 | Logistic & Transport | SPT |
| 710 | Others Service | SPT & GN |

## Verified against item data in the sheets

- Non-Stock 900–908 and Service 700–710: all existing codes conform (`middle 4 digits = 0000`), running mostly contiguous. Current max per group captured (e.g. 700→0206, 705→0248, 900→0203).
- Stock: groups 801/802/803/805 conform. **Group 800 does NOT fully conform** — real item numbers include `80001800___`, `80003100___`, … `80004200137` (middle digits 018, 031, 034, 039, 040, 041, 042 ≠ 0000). Looks like a machine/sub-group segment similar to the Mould pattern. **Needs confirmation.**
- The "Search name" column carries a second code series (e.g. Item `80000000048` ↔ search name `80001000001`) — 953 codes appear only in Search name. Purpose unclear. **Needs confirmation.**

## Open questions

1. Group 800: what are the middle 3–4 digits (018/031/…/042)? Machine code? Where is the reference list?
2. Search-name second code series — legacy mapping or planned renumbering? Should the new system care?
3. Scope owner SPT vs GN — does this affect who may request which group, or only informational?
