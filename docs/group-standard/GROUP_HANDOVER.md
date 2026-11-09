# _HANDOVER — Carabao Group Item Master Restructure

> **หยุดอัปเดตตั้งแต่ 3 ส.ค. 2026 / Not updated since 2026-08-03.** เก็บไว้เป็น
> ประวัติและที่มาของมาตรฐานกลุ่ม สถานะปัจจุบันอยู่ที่ `docs/IT-HANDOVER.md` และ
> `docs/HANDOFF.md` (เช่น D1–D4 ใช้แล้วตั้งแต่ 2026-08-06, master สุดท้ายคือ
> `Central_v5_with_DCM`) / Kept as the history of the group standard; current
> status is in `docs/IT-HANDOVER.md` and `docs/HANDOFF.md`. The pipeline and
> source files it lists are outside this repo (`docs/IT-HANDOVER.md` C3).

> อัปเดตล่าสุด: 3 ส.ค. 2026 · เจ้าของงานตอนนั้น / owner then: Peter — Procurement Strategy, Carabao Group
>
> **ตั้งแต่ 2026-11-13 ที่ไหนที่ Peter เป็นผู้ตัดสินใจหรืออนุมัติ ให้อ่านเป็น
> `[BUSINESS-OWNER]`** (เช่น "ห้ามเปลี่ยนโดยไม่ถาม Peter") ที่อยู่ไฟล์ปัจจุบัน
> ดู `docs/IT-HANDOVER.md` C3 (OneDrive ของ Peter จนกว่าจะย้ายเสร็จ แล้วจึงเป็น PurchaseWFH) /
> From 2026-11-13, where Peter decides or approves, read `[BUSINESS-OWNER]`
> (`docs/IT-HANDOVER.md` C1). For where a file is now, see C3 (Peter's
> OneDrive until the move is done, then the PurchaseWFH team site).

---

## 1. โจทย์

โรงงานในเครือ Carabao ใช้ Item Master คนละรูปแบบกัน ทำให้เทียบ spend ข้ามโรงงานไม่ได้

- **ACM / APM / APG** — ใช้รูปแบบเดียวกันทั้งสามโรงงาน รันรหัสร่วมกัน รหัส 11 หลักตัวเลขล้วน
- **CBD** — ใช้รหัส 10 หลักผสมตัวอักษร (`64XX999999`) คนละรูปแบบสิ้นเชิง

**เป้าหมายที่ Peter ยืนยันแล้ว (แผน B):** ทุกโรงงานใช้ **รหัสเดียวกันหมด** — 1 รายการ = 1 รหัส ไม่ว่าโรงงานไหนเปิด

**ขอบเขต:** เฉพาะสินค้าไม่เข้า stock และงานบริการ
- ฝั่ง CBD = รหัสขึ้นต้น `64` เท่านั้น (7,700 รายการ)
- **ห้ามแตะรหัสขึ้นต้น `99` ของ CBD เด็ดขาด** — เป็นสินค้าเข้า stock มีทีมของ "พี่นิคม" ดูแลอยู่ กำลังแปลงเป็นตระกูล 8xx
- ฝั่ง ACM/APM/APG = ไฟล์ Non-Stock (9xx) + Service (7xx) รวม 11,377 รหัส

---

## 2. โครงสร้างที่ตกลงกันแล้ว (อนุมัติแล้ว ห้ามเปลี่ยนโดยไม่ถาม Peter)

### รหัส 11 หลัก

```
9 0 0   0 1   0 0   0 0 0 1
└─┬─┘   └┬┘   └┬┘   └──┬──┘
  │      │     │       └──── Running 4 หลัก — จากทะเบียนกลางชุดเดียวต่อคู่ Category+Sub
  │      │     └──────────── Item Type 2 หลัก — สงวนไว้ = "00" เสมอในเฟสนี้
  │      └────────────────── Sub-Category 2 หลัก (01-99)   ← ระดับ 2
  └───────────────────────── Item Group 3 หลัก             ← ระดับ 1
```

**หลักประกันไม่ชนรหัสเดิม:** รหัสเดิมของ ACM/APM/APG ทั้ง 11,377 รหัส มีหลัก 4-7 = `0000` ทุกตัวไม่มีข้อยกเว้น
รหัสใหม่ใช้ Sub-Category ≥ `01` เสมอ → ชนกันไม่ได้ทางคณิตศาสตร์

### Taxonomy 2 ระดับ

20 Item Group (7xx = Service 11 กลุ่ม · 9xx = Non-Stock 9 กลุ่ม) · **105 Sub-Category**
→ รายละเอียดครบอยู่ในชีต `Taxonomy` ของไฟล์ Central และใน `_pipeline/rules.py` ตัวแปร `TAX`

### Naming convention

```
[CATEGORY] - [ชื่อสินค้า/บริการ] - [รายละเอียดจำเพาะ]     ยาวไม่เกิน 110 ตัวอักษร
```

- ตัวคั่นคือ ` - ` (เว้นวรรค-ขีด-เว้นวรรค) **เท่านั้น** ห้ามใช้ `--` `:` `/` `,`
- ภาษาแบบ **Hybrid** (Peter เลือกเอง): CATEGORY prefix / ยี่ห้อ / รุ่น / หน่วย = อังกฤษเสมอ · ชื่อสามัญที่หน้างานเรียกไทย = ไทย
- ห้ามมีคำว่า `(ยกเลิก)` ในชื่อ — ใช้ `Lifecycle State = Blocked` แทน

### Marketing (908 / 706) — มาจากไวท์บอร์ด Canva ของ Peter

ไวท์บอร์ดต้นฉบับ: `Category-GN` https://www.canva.com/design/DAGzYhDOWyM/2K6O_ncRCHyRkmzthXjGww/edit
(เปิดได้ด้วย Canva connector — `read-design` แล้วใส่ URL ตรงๆ)

Peter ทำ taxonomy ไว้ 5 Category / 24 Sub-Category พร้อมคำนิยามครบทุกตัว ผมปรับ 4 จุดและ **Peter อนุมัติแล้ว**:

1. **ยก Category 5 ตัวเดิม (POSM / Merchandise / Event Production / DR Consultant / Media) ขึ้นเป็น attribute `Marketing Activity`** — เพราะ `Installation & Maintenance`, `Travel & Accommodation`, `Labour Cost` ซ้ำอยู่ใต้ 2 Category ทำให้ 3 concept กลายเป็น 6 รหัส
2. เพิ่ม `Content & Creative Production` (23 รายการ) และ `Agency & Management Fee` (5 รายการ) ที่เดิมไม่มีบ้าน
3. แยกของ/บริการเข้า 908 / 706 ตามมาตรฐานกลุ่ม
4. แก้นิยาม `Garments & Apparel` ให้แคบลง (เดิมกินยูนิฟอร์มโรงงาน 18 รายการ) · เกณฑ์คือ **"ใครใส่ เพื่ออะไร" ไม่ใช่ "ใครซื้อ"**

`Travel & Accommodation` และ `Transportation` ย้ายไปกลุ่มกลาง (710-02 / 709-01) เกณฑ์คือ *"ถ้าแผนกอื่นซื้อของสิ่งเดียวกันนี้ ได้ของเหมือนกันไหม"*

### การตัดสินใจอื่นที่ Peter ยืนยันแล้ว

| ประเด็น | คำตัดสิน |
|---|---|
| ความเข้มในการรวมรายการซ้ำ | **Conservative** — รวมเฉพาะชื่อตรงกันสนิทหลัง normalize **และ** อยู่หมวดย่อยเดียวกัน |
| SVSP 292 รายการ (ปนบริการ+อะไหล่) | **แตกเป็น 2 รหัส** เฉพาะตัวที่มีคำกริยางานบริการ (Repair/PM/Install/Overhaul/MA) → ได้ 146 ตัว |
| MC 13 + VE 3 (เครื่องจักร/รถ) | ลง Needs_Review รอ Accounting ยืนยัน Fixed Asset |
| UoM | Derive จากชื่อ ที่เหลือตั้งค่าเริ่มต้น EA/JOB + ทำเครื่องหมาย `Default (ต้องยืนยัน)` |
| รหัส 800/803/805 หลุดในไฟล์ ACM | เดินหน้าต่อได้ แต่บันทึกเป็น open issue (ชนกับช่วงที่ทีม Stock CBD ใช้) |
| Group 908 Marketing ว่างเปล่าใน ACM | เพราะ ACM ไม่เคยซื้อของ Marketing → **CBD เป็นผู้ใช้รายแรก taxonomy ของ CBD จึงกลายเป็นมาตรฐานกลุ่ม** |

---

## 3. สถานะปัจจุบัน — ทำอะไรไปแล้ว

ผลรัน ณ 3 ส.ค. 2026:

| | จำนวน |
|---|---|
| รายการเดิมทั้งหมด | 19,077 (CBD 7,700 + ACM/APM/APG 11,377) |
| บรรทัดใน Mapping | 19,223 (เกินมา 146 เพราะ SVSP แตกรหัส) |
| **รหัสกลางที่ออกให้** | **13,326** — จาก ACM/APM/APG 5,823 · CBD 7,503 |
| ถูกรวม — ซ้ำข้ามโรงงาน | 101 |
| ถูกรวม — ซ้ำในโรงงานเดียวกัน | 189 |
| รอตัดสินใจ (ยังไม่ออกรหัส) | 291 |
| บล็อกรหัสสำรองของ ACM (ไม่ยกมา) | 5,316 |
| Clean (หมวดย่อยชัดเจน) | 72.9% |

ผ่านการตรวจสอบอัตโนมัติ 12 ข้อ รวมถึง: รหัสเดิมอยู่ครบไม่หายแม้แต่ตัวเดียว · รหัสใหม่ไม่ซ้ำ · ไม่ชนรหัส ACM/APM/APG 11,377 รหัส

### 2 ข้อค้นพบสำคัญที่ต้องรู้

**ก. รหัสของ ACM/APM/APG 5,316 จาก 11,377 (47%) ไม่ใช่รายการจริง**
เป็นบล็อกที่ generate ไว้ล่วงหน้า พิสูจน์แล้ว: ในทุกกลุ่ม รหัสที่ไม่มีชื่อ**อยู่ท้ายแถวต่อจากรหัสสุดท้ายที่ใช้งานจริง 100%** ไม่มีตัวไหนแทรกกลางเลย
ตัวอย่าง: กลุ่ม 704 มี 2,250 รหัส มีชื่อจริงแค่ 36 · กลุ่ม 705 มี 588 รหัส มีชื่อจริงแค่ 6

**ข. ACM/APM/APG จัดของลงกลุ่มไม่ตรงกับ taxonomy 1,660 รายการ (29% ของรายการจริง)**
เช่น เครื่องมือช่างอยู่ในกลุ่ม 905 Factory Consume · น้ำยาทำความสะอาดอยู่ในกลุ่ม 906 General Consume
**ตัดสินใจ: จัดใหม่ตามชื่อสินค้า ไม่ยึดกลุ่มเดิม** เพราะยึดกลุ่มเดิม = ยกความผิดพลาดมาไว้ใน master ใหม่ แต่ flag ทุกตัวไว้ให้ veto ได้

---

## 4. รออะไรอยู่ — งานถัดไปคือข้อนี้

**Peter กำลังกรอก `Carabao_Item_Master_Decision_Sheet.xlsx`**

ยุบการรีวิว 5,249 รายการ ให้เหลือการตัดสินระดับ "รูปแบบ" **304 ครั้ง**:

| ชีต | จำนวน | เคลียร์ได้ | คำตอบที่รับ |
|---|---|---|---|
| D1 บล็อกรหัสสำรอง | 19 | 5,316 รหัส | A = ทิ้ง · B = ของจริงต้องหาชื่อ |
| D2 การย้ายกลุ่ม | 124 | 1,660 รายการ | A = อนุมัติ · B = คงกลุ่มเดิม · C = ไปกลุ่มอื่น (ระบุ) |
| D3 รายการที่ยังไม่ออกรหัส | 6 | 291 รายการ | A = ตัดออก · B = Blocked · C = หาข้อมูลเพิ่ม · D = จัดเข้าหมวด |
| D4 คำสำคัญในหมวด Other | 155 | ส่วนใหญ่ของ 3,508 | ใส่เลขหมวดย่อย 2 หลัก |

**พอ Peter ส่งกลับมา ให้ทำ:**
1. อ่านคำตอบจากชีต D1-D4
2. D4 → แปลงเป็น rule ใหม่ใส่ใน `rules.py` (คำ → sub-category)
3. D2 → ถ้าตอบ B ให้ pin กลุ่มเดิมไว้ · ถ้า C ให้ย้ายตามที่ระบุ
4. D1/D3 → ตัดออกหรือยกมาตามคำตอบ
5. รัน pipeline ใหม่ทั้งชุด → ออกรหัสรอบสุดท้าย
6. **สำคัญ:** รหัสต้องออกครั้งเดียวจบ อย่าให้ user ต้องจำรหัสใหม่สองรอบ

---

## 5. ไฟล์ในโฟลเดอร์นี้

### ข้อมูลต้นทาง (ห้ามแก้)
| ไฟล์ | คืออะไร |
|---|---|
| `All Item (CBD).xlsx` | Item Master ปัจจุบันของ CBD — ใช้ sheet `All Item` · กรอง `Item number` ที่ขึ้นต้น `64` |
| `Non-Stoock (APM,APG,ACM).xlsx` | Non-Stock ของ 3 โรงงาน (9xx) — ทุก sheet ยกเว้น `Item Groups` |
| `Service (APM,APG,ACM).xlsx` | Service ของ 3 โรงงาน (7xx) — โครงสร้างเดียวกัน |
| `Item Stock (CBD) - New.xlsx` | งานของทีมพี่นิคม (สินค้าเข้า stock → 8xx) **อ้างอิงเท่านั้น ห้ามแตะ** |

### ผลลัพธ์ปัจจุบัน
| ไฟล์ | คืออะไร |
|---|---|
| `Carabao_Group_Item_Master_Central_v1.xlsx` | **ไฟล์หลัก** — Summary / Mapping / New_Item_Master / Taxonomy |
| `Carabao_Group_Item_Master_Review_v1.xlsx` | Duplicates / Needs_Review / Regrouped / Reserved_Codes / Duplicates_Near |
| `Carabao_Item_Master_Decision_Sheet.xlsx` | **ไฟล์ที่รอ Peter กรอก** |
| `CBD_NonStock_Restructure_Proposal_v1.md` | เอกสารวิเคราะห์ + Target Structure (ข้อ 1-2 ที่อนุมัติแล้ว) |
| `CBD_Marketing_Taxonomy_Review_v2.md` | รีวิวไวท์บอร์ด Marketing ฉบับที่อ่านของจริงแล้ว (**v1 ผิด ทิ้งได้**) |
| `CBD_NonStock_Item_Master_Migration_v1.xlsx` | ผลลัพธ์แผน A (ทำเฉพาะ CBD) เก็บไว้เทียบให้ผู้บริหารดู |

### `_pipeline/` — script ทั้งหมด

รันตามลำดับนี้ (แต่ละไฟล์อ่าน/เขียน pickle ใน `/tmp`):

```
1. transform.py      CBD: จัดหมวด + แตก SVSP        -> /tmp/w.pkl
2. build_output.py   CBD: ตั้งชื่อ + UoM + dedup     -> /tmp/m.pkl, /tmp/m2.pkl
3. groupwide.py      ACM: จัดหมวด + รวมกับ CBD       -> /tmp/all.pkl, /tmp/ref_raw.pkl
4. gw_build.py       ตั้งชื่อ + dedup ข้ามโรงงาน + ออกรหัสกลาง -> /tmp/gw.pkl
5. gw_sheets.py      สร้าง dataframe ของทุกชีต       -> /tmp/gw_*.pkl
6. gw_write.py       เขียน Excel 2 ไฟล์              -> /tmp/gw_master.xlsx, /tmp/gw_review.xlsx
7. dec.py + decw.py  สร้าง Decision Sheet            -> /tmp/dec.xlsx
```

`rules.py` = หัวใจทั้งหมด — `TAX` (taxonomy 130 รายการ) · `MKT_ACTIVITY` · rule chain ต่างๆ (MECH, ELEC, TOOLS, PAINT, LUBE, CLEANCHEM, MKT, SVC, EXTRA_*)

`make_xlsx.py` + `write_xlsx.py` = ของแผน A (CBD อย่างเดียว) เก็บไว้เผื่อต้องอัปเดตไฟล์เทียบ

---

## 6. กับดักที่เจอมาแล้ว — อย่าพลาดซ้ำ

### 6.1 `\b` ใน regex พังกับภาษาไทย ⚠️ สำคัญที่สุด

สระและวรรณยุกต์ไทยเป็นอักขระ **non-word** ใน Python regex ทำให้ `\bสี\b` ไปจับคำว่า "สีดำ" "สีเขียว" ได้
→ หมวกนิรภัยกับรองเท้าเซฟตี้ 64 รายการเคยตกไปอยู่กลุ่ม Chemicals

**ห้ามใช้ `\b` ติดกับตัวอักษรไทยเด็ดขาด** ใช้ `(?<![ก-๙])` / `(?![ก-๙])` แทน
ตอนนี้ใน `rules.py` แก้หมดแล้ว 7 จุด (สี ท่อ ธง มีด รอก เช่า แอร์)

### 6.2 `unicodedata.normalize('NFKC')` ทำสระ ำ แตกตัว

NFKC แยก `ำ` (U+0E33) เป็น `ํ` + `า` ทำให้ keyword ไทยไม่ match เลย
→ **ใช้ `NFC` เท่านั้น** และเรียก `fix_thai()` ที่ทำ `.replace('ํา','ำ')` ตามหลัง

### 6.3 recalc.py ช้ามาก ถ้าทำผิดวิธี

| ปัญหา | วิธีแก้ |
|---|---|
| รันบนโฟลเดอร์ mount (`/sessions/.../mnt/`) ช้ากว่า `/tmp` เป็นเท่าตัว | **สร้างและ recalc ใน `/tmp` แล้วค่อย `cp` ไปโฟลเดอร์** |
| override named style (`wb._named_styles[0].font`) ทำให้ LibreOffice ช้ามาก | ตั้ง font ที่ **column level** (`column_dimensions[X].font`) |
| ไฟล์ใหญ่เกิน ~15,000 แถวรวม จะเกิน 45 วินาที | แยกเป็น 2 workbook (Central / Review) |
| COUNTIF ข้ามชีตใหญ่ๆ ช้า | ใช้ชีตซ่อน `_calc` ที่มีเฉพาะคอลัมน์ที่ต้องนับ |
| bash timeout 45 วิ · background process ไม่รอดข้ามคำสั่ง | ต้องให้ recalc จบใน 1 คำสั่ง อย่าใช้ `nohup &` |

### 6.4 เขียนทับไฟล์ในโฟลเดอร์ไม่ได้บางครั้ง

ถ้า Peter เปิดไฟล์ค้างใน Excel จะ `Permission denied` — ให้บอกเขาปิดไฟล์แล้วลองใหม่ · `rm` บนโฟลเดอร์นี้ใช้ไม่ได้เลย ต้องให้ Peter ลบเอง

### 6.5 path ของ session เปลี่ยนทุกครั้ง

script ใน `_pipeline/` hardcode path `/sessions/focused-lucid-goldberg/...` ไว้
**ก่อนรันครั้งแรกต้องแก้ path ให้ตรงกับ session ใหม่:**

```bash
NEW=$(ls -d /sessions/*/mnt | head -1 | xargs dirname)
cd "<โฟลเดอร์ _pipeline ใน session ใหม่>"
sed -i "s|/sessions/focused-lucid-goldberg|$NEW|g" *.py
```

---

## 7. สิ่งที่ยังไม่ได้ทำเลย (ช่องโหว่จริง)

1. **Cutover plan** — เปลี่ยนรหัสทุกตัวทั้งกลุ่มกระทบ PO ที่เปิดค้าง · BOM/สูตร · สัญญาที่อ้างรหัส · ประวัติ spend · รายงานที่ hardcode รหัส **ยังไม่มีแผนตัดเลย นี่คือความเสี่ยงที่ใหญ่กว่าตัวข้อมูล**
2. **Governance workflow** — ใครขอเปิด item · ใครอนุมัติ · ต้องค้นก่อนเปิดยังไง · ใครเป็น data steward · KPI วัดคุณภาพ
3. **ทะเบียนเลขรันกลาง** — ยังไม่มีเจ้าของ **ถ้าไม่มี รหัสจะกลับมาชนภายในเดือนแรก**
4. UoM master + Abbreviation dictionary ยังเป็นแค่ตัวแปรใน script ยังไม่เป็นเอกสารมาตรฐาน

---

## 8. วิธีคุยกับ Peter

- ตอบเป็น**ภาษาไทย** ศัพท์เทคนิคเป็นอังกฤษ
- **กระชับ ตรงประเด็น** เขาไม่ชอบคำอธิบายฟุ่มเฟือย
- เขา**ตัดสินใจเองได้** ไม่ต้องโยนไปให้แผนกอื่นถ้าไม่จำเป็นจริง
- เจอปัญหาให้**บอกตรงๆ พร้อมตัวเลข** อย่ากลบ — เขาให้ค่ากับความตรงไปตรงมามากกว่าข่าวดี
- เวลาเสนอทางเลือก ให้**แนะนำมาเลยว่าควรเลือกอันไหนและเพราะอะไร**
- อย่ารีวิวทีละรายการเมื่อยุบเป็นรูปแบบได้ — เขาชอบวิธีที่ลดจำนวนการตัดสิน
