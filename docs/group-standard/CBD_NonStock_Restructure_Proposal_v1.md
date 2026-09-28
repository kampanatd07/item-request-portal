# CBD Non-Stock Item Master Restructure
## ข้อ 1 — วิเคราะห์เปรียบเทียบ | ข้อ 2 — Target Structure (รอ Peter อนุมัติ)

เอกสารฉบับที่ 1 · 3 ส.ค. 2026 · Procurement Strategy, Carabao Group
ขอบเขต: CBD item code ที่ขึ้นต้นด้วย `64` เท่านั้น (7,700 รายการ) — **ไม่แตะ `99xxx`**

---

# ส่วนที่ 1 — วิเคราะห์เปรียบเทียบ

## 1.1 มาตรฐาน ACM / APM / APG (ปลายทาง)

### โครงสร้างรหัส — 11 หลัก

จากไฟล์ reference ทั้งสอง (Non-Stock + Service) พบรหัสที่ใช้จริงแล้ว **11,377 รหัส** ทุกรหัสยาว 11 หลักและตรงตามสูตรเดียวกัน:

```
7 0 2   0 0 0 0   0 0 8 4
└─┬─┘   └──┬──┘   └──┬──┘
  │        │         └── Running number (หลัก 8-11) เริ่มจาก 0001
  │        └──────────── หลัก 4-7 : ปัจจุบัน "0000" ทุกรหัส 100%
  └───────────────────── Item Group 3 หลัก
```

**ข้อค้นพบสำคัญ:** หลัก 4-7 เป็น `0000` ทั้ง 11,377 รหัส — ไม่มีข้อยกเว้นเลย  
แต่ทีม Stock ของ CBD (ไฟล์ `Item Stock (CBD) - New`) ได้ออกแบบให้หลัก 4-7 แตกเป็น **Sub-Group (หลัก 4-5) + Item Type (หลัก 6-7)** แล้ว

→ แปลว่ารูปแบบจริงของกลุ่มบริษัทคือ:

```
Item Group (3) + Sub-Group (2) + Item Type (2) + Running (4) = 11 หลัก
```

และ ACM/APM/APG คือกรณี Sub-Group = `00`, Item Type = `00` **นี่คือช่องว่างที่ CBD ใช้ได้ทันทีโดยไม่ชนรหัสเดิม**

### Item Group ที่ใช้อยู่ และปริมาณรหัสที่ถูกจองไปแล้ว

| Group | ชื่อ | Scope | รหัสที่จองแล้ว | Running สูงสุด |
|---|---|---|---|---|
| **700** | Installation & Repair Machinery | SPT | 749 | 0749 |
| **701** | Construction & Civil & Utility | SPT | 138 | 0138 |
| **702** | Calibration & Certification Service | SPT | 1,643 | 1643 |
| **703** | Tools & Electrical Equip. Service | SPT | 50 | 0050 |
| **704** | Safety & Environmental Service | SPT | 2,250 | 2250 |
| **705** | Rental | SPT | 588 | 0588 |
| **706** | Marketing Service | GN | 50 | 0050 |
| **707** | IT Software & Service | GN | 133 | 0133 |
| **708** | Generals Service | GN | 50 | 0050 |
| **709** | Logistic & Transport | SPT | 50 | 0050 |
| **710** | Others Service | SPT&GN | 73 | 0073 |
| **900** | Spare Parts & Mechanical Parts | SPT | 2,152 | 2152 |
| **901** | Electrical Parts | SPT | 561 | 0561 |
| **902** | Lab Instruments | SPT | 349 | 0349 |
| **903** | Chemicals (Oil & Gas) | SPT | 124 | 0124 |
| **904** | Construction Materials | SPT | 172 | 0172 |
| **905** | Factory Consume | SPT | 963 | 0963 |
| **906** | General Consume | GN | 688 | 0688 |
| **907** | IT Hardware & Accessories | GN | 588 | 0588 |
| **908** | Marketing | GN | 0 | — |

> **ประเด็นต้องยืนยัน:** Group 908 (Marketing) ยังไม่มีรหัสที่ใช้จริงเลย (sheet ว่างทั้งหมด) — ต้องเช็คว่ายังไม่เปิดใช้ หรือเก็บอยู่คนละไฟล์  
> **ประเด็นเพิ่มเติม:** พบรหัสหลุด 6 รหัสในตระกูล 800/803/805 ปนอยู่ในไฟล์ Non-Stock (เช่น `80000000645`, `80300000063`, `80500000710`) ซึ่งชนกับที่ทีม Stock CBD กำลังจะใช้ (800, 807-811) — **ต้องเคลียร์ก่อนทั้งสองทีมเดินต่อ**

### Naming convention

ACM/APM/APG **ไม่มี naming convention ที่บังคับใช้จริง** — เป็น free text  
สังเกตจากตัวอย่าง: `ยางยอยสีเหลือง ROTEX GR28`, `Power Supply: MEAN WELL LRS-75`, `Hand Tool: Deep Socket 22mm (B4L-22W)`, `งานสอบเทียบเครื่อง Leica DMC2900 camera&SW kit`

รูปแบบที่ *พอเห็นเป็นแนวโน้ม* (แต่ไม่สม่ำเสมอ):
- ไทย-อังกฤษปนกัน โดยของที่มียี่ห้อ/สเปกใช้อังกฤษ ของทั่วไปใช้ไทย
- บางส่วนใช้ `[Noun]: [Brand] [Model]` ด้วยเครื่องหมาย `:` แต่ใช้ไม่ถึง 20% ของรายการ

**สรุป: ฝั่งปลายทางเองก็ยังไม่มีมาตรฐานชื่อ** → เป็นโอกาสให้ CBD เป็นผู้กำหนดมาตรฐานให้ทั้งกลุ่ม แทนที่จะไปลอกความไม่เป็นระเบียบมา

### Attribute ที่มีในไฟล์ปลายทาง

`Item number` · `Product name` · `Item group` (ค่า `EN-FS` เพียงค่าเดียว และเติมแค่ 1,097 จาก 11,377 = **10%**) · `Search name` · `Product type` (Item/Service) · `Product subtype` · `Product service type` · `Product dimension groups` (ว่างทั้งหมด) · `Product lifecycle state` (ว่างทั้งหมด) · `Item model group` (ว่างทั้งหมด)

### มาตรฐานหน่วยนับ

**ไม่มี** — ไฟล์ปลายทางไม่มีคอลัมน์ UoM เลย ทั้ง Inventory unit / Purchase unit / Sales unit  
หน่วยนับฝังอยู่ในชื่อสินค้าแบบไม่มีมาตรฐาน: `20 kg.`, `(18L)`, `(100/PK)`, `1/208LT.`, `(40Plates/Box)`, `5 ลิตร`, `47L`

---

## 1.2 CBD ปัจจุบัน (64xxx)

### โครงสร้างรหัส

```
6 4   F Q   0 0 0 0 0 1
└┬┘   └┬┘   └────┬────┘
 │     │         └── Running 6 หลัก
 │     └──────────── รหัสหมวด 2 ตัวอักษร
 └────────────────── คงที่ "64" = non-stock
```

**10 หลัก · ผสมตัวอักษร** — ไม่สามารถเข้ากับระบบรหัสตัวเลข 11 หลักของกลุ่มได้เลย และเรียงลำดับ/รวมรายงานข้ามโรงงานไม่ได้

### หมวดหมู่ปัจจุบัน 19 รหัส (+1 รหัสผิดรูป)

| รหัส | ความหมายที่ตีความได้ | จำนวน | Item | Service |
|---|---|---|---|---|
| FQ | Factory Equipment / อะไหล่กลไก | 2,461 | 2,460 | 1 |
| SV | Service งานบริการ | 1,074 | 677 | 397 |
| BD | Building / งานอาคาร-สาธารณูปโภค | 789 | 782 | 7 |
| IT | IT | 650 | 586 | 64 |
| FL | Forklift | 465 | 458 | 7 |
| CS | Consumable / Supply (ปนหลายอย่าง) | 397 | 397 | 0 |
| OF | Office | 384 | 384 | 0 |
| LQ | Lab Quality / วัสดุห้องแล็บ | 377 | 377 | 0 |
| WF | Welfare / ยูนิฟอร์ม-ยา | 287 | 287 | 0 |
| SP | Spare Parts | 240 | 240 | 0 |
| MD | Marketing / สื่อ | 225 | 184 | 41 |
| MS | Miscellaneous Supply | 106 | 103 | 3 |
| SF | Safety / PPE | 106 | 106 | 0 |
| CH | Chemical (แล็บ) | 93 | 93 | 0 |
| OT | Others | 18 | 18 | 0 |
| MC | Machine (เครื่องจักร) | 13 | 13 | 0 |
| FU | Fuel & Gas | 9 | 9 | 0 |
| TR | Travel | 3 | 2 | 1 |
| VE | Vehicle | 3 | 3 | 0 |
| **SVSP** | Service+Spare bundle (รหัสผิดรูป) | 292 | 292 | 0 |

### ความต่างหลัก CBD vs ACM/APM/APG

| ประเด็น | CBD วันนี้ | ACM/APM/APG | ผลกระทบ |
|---|---|---|---|
| ความยาว/ชนิดรหัส | 10 หลัก มีตัวอักษร | 11 หลัก ตัวเลขล้วน | **ต่างสิ้นเชิง — รวมรายงานไม่ได้** |
| จำนวนหมวด | 19 + 1 ผิดรูป | 20 (11 service + 9 non-stock) | ใกล้เคียงกัน แต่ mapping ไม่ตรง 1:1 |
| แยก Service ออกจาก Item | ไม่แยก — SV ปนทั้ง Item และ Service | แยกชัด: 7xx = Service, 9xx = Non-Stock | CBD ทำ spend analysis แยก goods/services ไม่ได้ |
| Sub-category | ไม่มี | ไม่มี (แต่โครงสร้างรองรับ) | ทั้งสองฝั่งไม่มี — ต้องสร้างใหม่ |
| Category เป็นคอลัมน์แยก | ไม่มี (ฝังในรหัส) | ไม่มี (ฝังในรหัส) | report ต้อง parse รหัส เปราะมาก |
| หน่วยนับ | ไม่มี ฝังในชื่อ | ไม่มี ฝังในชื่อ | ทั้งกลุ่มไม่มี UoM master |
| Naming | free text | free text | ทั้งกลุ่มไม่มีมาตรฐาน |

---

## 1.3 ปัญหาคุณภาพข้อมูลฝั่ง CBD (64xxx = 7,700 รายการ)

| # | ปัญหา | จำนวน | % | ตัวอย่าง |
|---|---|---|---|---|
| 1 | **รายการซ้ำ — ชื่อเหมือนกันเป๊ะ** | 85 กลุ่ม / **176 รายการ** | 2.3% | `64SV000450` & `64SV000458` = `งานสอบเทียบ Electronic Balance` |
| 2 | **รายการซ้ำ — เหมือนหลัง normalize** | 100 กลุ่ม / **206 รายการ** | 2.7% | `Medicine - ยาลดกรด - Antacil` vs `Medicine - ยาลดกรด Antacil` |
| 3 | **ใกล้เคียงกันมาก (similarity ≥ 0.80)** | 1,633 คู่ / **1,116 รายการ** | **14.5%** | ต้องรีวิวว่าซ้ำจริงหรือต่างสเปก |
| 4 | **ซ้ำข้ามหมวด (SV ↔ SVSP)** | ~40 คู่ | — | `64SV000723` & `64SVSP0224` = `TECHNICAL SERVICE CHARGE` |
| 5 | **ชื่อว่าง / เป็นจุด "." / ขยะ** | **104 รายการ** | 1.4% | `64FQ01093` = `.`, `64WF000xxx` = `.` |
| 6 | **รายการที่ยกเลิกแล้วยังอยู่ในระบบ** | **34 รายการ** | 0.4% | `64SF000001` = `(ยกเลิก) ชุด PPE` |
| 7 | **รหัสผิดรูป (ยาวไม่เท่ากัน)** | 42 รายการ | 0.5% | 9 หลัก 39 รายการ (`64FQ01093`), 11 หลัก 3 รายการ (`64SVSP00027`) |
| 8 | **`Product type` ผิด — บริการถูกตั้งเป็น Item** | ≥ **677 รายการ** ในหมวด SV | 8.8% | `64SV000543 งานสอบเทียบ pH meter` = Item ทั้งที่เป็นงานบริการ |
| 9 | **หมวด SVSP ปนบริการกับอะไหล่ในรหัสเดียว** | **292 รายการ** | 3.8% | `Repair Air Blower--Asset & Spare parts` — แยก spend ไม่ได้ |
| 10 | **หน่วยนับไม่มีเลย + ฝังในชื่อแบบไม่สม่ำเสมอ** | **7,700 รายการ** | **100%** | `20 ลิตร` / `(18L)` / `1/208LT.` / `(100/PK)` |
| 11 | **ภาษาปนกันไม่มีกฎ** | mixed 3,851 (50%) · EN 2,636 (34%) · TH 1,109 (14%) | — | ค้นหาไม่เจอเพราะไม่รู้ว่าคำไหนถูกพิมพ์ภาษาอะไร |
| 12 | **เครื่องหมายคั่นขยะ / ชื่อขึ้นต้นด้วยตัวคั่น** | 244 รายการใช้ `--` · 104 รายการขึ้นต้นด้วย `. - / ,` | 4.5% | `อุปกรณ์ /หลอดเป่าแอลกอฮอล์`, `ชุดตรวจ ,Funnel 100 ml` |
| 13 | **`Search name` ไม่ตรงกับ `Product name`** | 163 รายการ | 2.1% | ทำให้ผลค้นหาไม่ตรงกัน |
| 14 | **หมวดจัดผิดประเภทงบ — สินทรัพย์ปนอยู่ใน non-stock** | MC 13 + VE 3 = **16 รายการ** | 0.2% | `Heuft Prime (Myanmar Project)`, `รถกระบะ` — ควรเป็น Fixed Asset |
| 15 | **หมวด catch-all ที่ไม่มีความหมาย** | CS 397 + MS 106 + OT 18 = **521 รายการ** | 6.8% | CS ปนทั้งน้ำมันหล่อลื่น หลอดไฟ สีสเปรย์ ใบเลื่อย ถ่าน |

**คะแนนคุณภาพข้อมูลตั้งต้น (baseline):**

| KPI | ค่าปัจจุบัน | เป้าหมายหลัง migration |
|---|---|---|
| Completeness (ชื่อใช้งานได้จริง) | 98.6% | 100% |
| Uniqueness (ไม่ซ้ำ) | 97.3% (ชื่อ) / **85.5%** (นับใกล้เคียง) | ≥ 99.5% |
| Validity (รหัสถูกรูปแบบ) | 99.5% | 100% |
| Consistency (Product type ถูกต้อง) | ~91% | 100% |
| **UoM coverage** | **0%** | ≥ 95% |
| Category coverage (เป็นคอลัมน์แยก) | 0% | 100% |

---

# ส่วนที่ 2 — Target Structure ที่เสนอ (รออนุมัติ)

## 2.1 โครงสร้างรหัสใหม่

```
  9 0 0    0 1    0 0    0 0 0 1
  └─┬─┘    └┬┘    └┬┘    └──┬──┘
    │       │      │        └──── Running 4 หลัก (0001-9999) ต่อ Group+Sub
    │       │      └───────────── Item Type 2 หลัก — สงวนไว้ = "00"
    │       └──────────────────── Sub-Category 2 หลัก (01-99)  ← ระดับ 2
    └──────────────────────────── Item Group 3 หลัก (ใช้ของกลุ่มเดิม)  ← ระดับ 1
```

### หลักประกันว่าไม่ชนรหัสเดิม

รหัสของ ACM/APM/APG **ทุกรหัส** มีหลัก 4-7 = `0000`  
รหัสใหม่ของ CBD **ทุกรหัส** จะมีหลัก 4-5 ≥ `01`  
→ **เป็นไปไม่ได้ทางคณิตศาสตร์ที่จะชนกัน** ไม่ต้องพึ่งการจองเลขหรือการประสานงานรายวัน

### กฎการกำหนดรหัสให้แต่ละรายการ

1. ตัดสินก่อนว่า **Service หรือ Non-Stock** → เลือกช่วง 7xx หรือ 9xx
2. เลือก **Item Group (3 หลัก)** จากรายการ 20 กลุ่มของ ACM/APM/APG — ห้ามสร้างกลุ่มใหม่
3. เลือก **Sub-Category (2 หลัก)** จาก dictionary ในข้อ 2.2
4. **Item Type = `00`** เสมอในเฟสนี้ (สงวนไว้ให้ CBD ขยายชั้นที่ 3 ในอนาคต หรือให้ทีม Stock ใช้ต่อยอด)
5. **Running** เดินจาก `0001` ใหม่ **แยกอิสระในแต่ละคู่ Group+Sub** — ไม่ต้องรู้เลขล่าสุดของ ACM/APM/APG
6. ทศนิยม/ตัวอักษรห้ามใช้เด็ดขาด — ตัวเลขล้วน 11 หลัก

### ⚠️ ประเด็นที่ต้องยืนยันก่อนแปลงข้อมูลจริง

| # | ประเด็น | ทำไมต้องยืนยัน |
|---|---|---|
| A | **Sub-Category dictionary ต้องเป็นมาตรฐานระดับกลุ่ม ไม่ใช่ของ CBD คนเดียว** | ถ้าวันหนึ่ง ACM/APM/APG เริ่มใช้ Sub ≥ 01 ด้วย dictionary คนละชุด จะชนกันทันที ต้องให้ MDM ส่วนกลางรับ dictionary นี้เป็นมาตรฐานเดียว |
| B | **รหัส 800/803/805 ที่หลุดอยู่ในไฟล์ Non-Stock ของ ACM (6 รหัส)** | ชนกับที่ทีม Stock CBD กำลังจะใช้ (800, 807-811) |
| C | **Group 908 Marketing ยังไม่มีข้อมูล** | ต้องรู้ว่าเปิดใช้แล้วหรือยัง ก่อน CBD ยิงรหัสเข้าไป |
| D | **Item Type = 00 หรือจะใช้เป็นรหัสโรงงาน** | ทางเลือก: ให้หลัก 6-7 = รหัสโรงงาน (CBD=01) เพื่อ trace ต้นทางรหัสได้ แต่จะเสียชั้นขยายไป |

---

## 2.2 Category Taxonomy — 2 ระดับ

### ฝั่ง Service (7xx)

| Group | Sub | Category / Sub-Category |
|---|---|---|
| **700** | | **Installation & Repair Machinery** |
| | 01 | Machine Installation |
| | 02 | Machine Repair |
| | 03 | Preventive Maintenance (PM / MA Contract) |
| | 04 | Overhaul |
| | 05 | Fabrication & Made-to-Order |
| | 06 | Forklift & Mobile Equipment Service |
| | 99 | Other Machinery Service |
| **701** | | **Construction & Civil & Utility** |
| | 01 | Civil & Building Work |
| | 02 | Utility System Work (น้ำ / ไฟ / ลม / ไอน้ำ) |
| | 03 | Renovation & Improvement |
| | 04 | Landscape & Exterior |
| | 99 | Other Construction Service |
| **702** | | **Calibration & Certification Service** |
| | 01 | Instrument Calibration |
| | 02 | Laboratory Analysis & Testing |
| | 03 | System & Building Certification |
| | 04 | Machine / Equipment Inspection |
| | 99 | Other Calibration Service |
| **703** | | **Tools & Electrical Equip. Service** |
| | 01 | Hand / Power Tool Repair |
| | 02 | Electrical Equipment Repair |
| | 03 | Air Conditioning Service |
| | 99 | Other Equipment Repair Service |
| **704** | | **Safety & Environmental Service** |
| | 01 | Waste Disposal |
| | 02 | Environmental Monitoring |
| | 03 | Pest Control |
| | 04 | Cleaning Service |
| | 05 | Security Service |
| | 06 | Hygiene & Sanitation Service |
| | 99 | Other SHE Service |
| **705** | | **Rental** |
| | 01 | Building & Space Rental |
| | 02 | Machine & Equipment Rental |
| | 03 | Vehicle Rental |
| | 99 | Other Rental |
| **706** | | **Marketing Service** |
| | 01 | Online Media |
| | 02 | Offline Media (TV / Radio / Print) |
| | 03 | Creative & Production |
| | 04 | Event & Activation |
| | 99 | Other Marketing Service |
| **707** | | **IT Software & Service** |
| | 01 | Software License & Subscription |
| | 02 | IT MA & Support Service |
| | 03 | System Development & Implementation |
| | 04 | Cloud & Hosting |
| | 99 | Other IT Service |
| **708** | | **Generals Service** |
| | 01 | Professional & Consulting Service |
| | 02 | Office Equipment & Furniture Repair |
| | 03 | Document & Printing Service |
| | 04 | Photography & Media Service |
| | 99 | Other General Service |
| **709** | | **Logistic & Transport** |
| | 01 | Domestic Transport |
| | 02 | Freight & Customs |
| | 03 | Packing & Handling |
| | 04 | Cargo Insurance |
| | 99 | Other Logistic Service |
| **710** | | **Others Service** |
| | 01 | Service Charge |
| | 02 | Travel & Accommodation |
| | 99 | Other |

### ฝั่ง Non-Stock (9xx)

| Group | Sub | Category / Sub-Category |
|---|---|---|
| **900** | | **Spare Parts & Mechanical Parts** |
| | 01 | Bearing & Power Transmission |
| | 02 | Seal, O-Ring & Gasket |
| | 03 | Fastener (น็อต สกรู แหวน) |
| | 04 | Pipe, Fitting & Valve |
| | 05 | Pneumatic & Hydraulic |
| | 06 | Pump, Motor & Gearbox Part |
| | 07 | Conveyor & Material Handling Part |
| | 08 | Filling / Packing Machine Part |
| | 09 | Forklift & Mobile Equipment Part |
| | 10 | Filter & Strainer |
| | 11 | Machine Structure & Fabricated Part |
| | 99 | Other Mechanical Part |
| **901** | | **Electrical Parts** |
| | 01 | Sensor & Instrument |
| | 02 | Control & Automation (PLC / HMI / Relay / Inverter) |
| | 03 | Power Distribution (Breaker / Contactor / Cable) |
| | 04 | Lighting |
| | 05 | Battery & Charger |
| | 06 | Motor & Electrical Drive |
| | 99 | Other Electrical Part |
| **902** | | **Lab Instruments** |
| | 01 | Glassware & Labware |
| | 02 | Lab Consumable (Filter / Tip / Plate) |
| | 03 | Lab Instrument & Spare Part |
| | 04 | Microbiology Test Kit |
| | 05 | Reference Standard & Calibration Material |
| | 99 | Other Lab Item |
| **903** | | **Chemicals (Oil & Gas)** |
| | 01 | Lab Reagent & Analytical Chemical |
| | 02 | Process & Water-Treatment Chemical |
| | 03 | Cleaning Chemical (CIP / COP / General) |
| | 04 | Lubricant & Grease |
| | 05 | Fuel & Industrial Gas |
| | 06 | Paint, Coating & Adhesive |
| | 99 | Other Chemical |
| **904** | | **Construction Materials** |
| | 01 | Civil & Structural Material |
| | 02 | Plumbing & Sanitary Material |
| | 03 | Building Hardware & Finishing |
| | 04 | Hand Tool & Power Tool |
| | 05 | Welding & Metalwork Consumable |
| | 99 | Other Construction Material |
| **905** | | **Factory Consume** |
| | 01 | Production Consumable |
| | 02 | Cleaning Equipment & Supply |
| | 03 | Marking, Labeling & Printing Consumable |
| | 04 | Packing & Wrapping Material (non-product) |
| | 05 | Measuring & Inspection Tool |
| | 99 | Other Factory Consumable |
| **906** | | **General Consume** |
| | 01 | Office Stationery & Paper |
| | 02 | Office Furniture & Equipment |
| | 03 | PPE & Safety Equipment |
| | 04 | Uniform & Employee Welfare |
| | 05 | Medical & First Aid |
| | 06 | Pantry & Housekeeping |
| | 99 | Other General Consumable |
| **907** | | **IT Hardware & Accessories** |
| | 01 | Computer & Peripheral |
| | 02 | Network & Communication Equipment |
| | 03 | Printer & Printing Supply |
| | 04 | Storage & Memory |
| | 05 | IT Accessory & Cable |
| | 99 | Other IT Hardware |
| **908** | | **Marketing** — *ปรับตามงานจัดกลุ่มของ Peter ดู `CBD_Marketing_Taxonomy_Review_v1.md`* |
| | 01 | Sticker & Wrap |
| | 02 | Flag & Banner |
| | 03 | Floor Standing & Display |
| | 04 | Shelf & Chiller POSM |
| | 05 | Signage & Printed Material |
| | 06 | Premium & Gift |
| | 07 | Marketing Apparel |
| | 08 | Event & Booth Equipment |
| | 09 | POSM Setup Material & Tool |
| | 99 | Other Marketing Item |

และหมวด **706 Marketing Service** ขยายเป็น 8 หมวดย่อย (Media Buying แยก Online / Broadcast / OOH+Print, Content Production, Agency Fee, Market Research, Event Service, Other) — รายละเอียดในเอกสารแนบฉบับที่ 2

**รวม 20 หมวดหลัก · 105 หมวดย่อย**

### แผน mapping จาก CBD เดิม → หมวดใหม่ (ประมาณการปริมาณ)

| CBD เดิม | จำนวน | ปลายทางหลัก | หมายเหตุ |
|---|---|---|---|
| FQ 2,461 | | 900 (ส่วนใหญ่) · 904 · 905 | ต้องแตกย่อยด้วยกฎคำสำคัญ |
| SV 1,074 | | 700-710 กระจาย | 397 เป็น Service, 677 ตั้ง type ผิด |
| BD 789 | | 904 · 905 · 903-03 · 906 | catch-all ต้องแตก |
| IT 650 | | 907 (586) · 707 (64) | แยก hardware ออกจาก service |
| FL 465 | | 900-09 · 903-04 · 700-06 | |
| CS 397 | | 901-04 · 903-04 · 903-06 · 904-04 | catch-all ต้องแตกหนัก |
| OF 384 | | 906-01 · 906-02 · 907 | |
| LQ 377 | | 902 | ตรงหมวดชัดเจน |
| WF 287 | | 906-04 · 906-05 | |
| SP 240 | | 900 | |
| MD 225 | | 908 (184) · 706 (41) | |
| MS 106 | | 905 · 906 | catch-all |
| SF 106 | | 906-03 | |
| CH 93 | | 903-01 · 902 | |
| OT 18 | | 905 · 906 / **Needs_Review** | |
| MC 13 | | **Needs_Review — น่าจะเป็น Fixed Asset** | ไม่ควรอยู่ non-stock |
| FU 9 | | 903-05 | |
| TR 3 | | 710-02 | |
| VE 3 | | **Needs_Review — Fixed Asset** | |
| SVSP 292 | | **Needs_Review — ต้องตัดสินเชิงนโยบายก่อน** | ปนบริการ+อะไหล่ในรหัสเดียว |

---

## 2.3 Naming Convention ใหม่

### รูปแบบ

```
[CATEGORY] - [ชื่อสินค้า/บริการ] - [รายละเอียดจำเพาะ]
```

| ส่วน | เนื้อหา | ภาษา | ความยาว |
|---|---|---|---|
| **CATEGORY** | ป้ายย่อของ Sub-Category ตัวพิมพ์ใหญ่ | อังกฤษเสมอ | ≤ 16 ตัวอักษร |
| **ชื่อสินค้า/บริการ** | Noun หลัก + ยี่ห้อ/รุ่น | Hybrid (ดูกฎด้านล่าง) | ≤ 50 |
| **รายละเอียดจำเพาะ** | ขนาด / สเปก / วัสดุ / บรรจุ | Hybrid | ≤ 40 |

รวมไม่เกิน **110 ตัวอักษร** (ปัจจุบัน CBD ยาวสุด 100 — ไม่กระทบใคร)

### กฎภาษา (Hybrid — ตามที่ Peter เลือก)

| ประเภทข้อมูล | ภาษา | ตัวอย่าง |
|---|---|---|
| CATEGORY prefix | **อังกฤษเสมอ** | `BEARING`, `PPE`, `CALIBRATION` |
| ยี่ห้อ / รุ่น / Part No. | **อังกฤษเสมอ ตามที่ผู้ผลิตเขียน** | `SKF 6001-2RSH`, `Philips TL-D90` |
| หน่วย / ขนาด / สเปกเทคนิค | **อังกฤษเสมอ** | `M12x1.75x40 mm`, `18 W`, `250 mL` |
| ชื่อสามัญที่มีศัพท์เทคนิคสากล | **อังกฤษ** | `Ball Bearing`, `Butterfly Valve`, `Safety Goggle` |
| ชื่อสามัญที่คนหน้างานเรียกเป็นไทย | **ไทย** | `น้ำยาล้างจาน`, `ปูนซีเมนต์`, `ชุดฟอร์มพนักงาน` |
| ชื่องานบริการ | **ไทย** ถ้าเป็นงานในประเทศ / **อังกฤษ** ถ้าเป็นสัญญาต่างประเทศ | `งานสอบเทียบ`, `MA Contract` |

### กฎเสริม (บังคับ)

1. ใช้ ` - ` (เว้นวรรค-ขีด-เว้นวรรค) เป็นตัวคั่นระดับเท่านั้น — **ห้ามใช้ `--`, `:`, `/`, `,` เป็นตัวคั่น**
2. ห้ามขึ้นต้นด้วยตัวคั่นหรือเครื่องหมายวรรคตอน
3. Noun หลักต้องมาก่อน modifier เสมอ (`Ball Bearing SKF` ไม่ใช่ `SKF Ball Bearing`)
4. ตัวเลข + หน่วย เว้นวรรค 1 ครั้ง และใช้หน่วย SI ตาม UoM master (`20 L` ไม่ใช่ `20ลิตร` / `20LT.` / `(20L)`)
5. ห้ามใส่คำว่า `(ยกเลิก)` ในชื่อ — ใช้คอลัมน์ `Lifecycle State = Blocked` แทน
6. ห้ามใส่ราคา ผู้ขาย เลข PO เลขที่เอกสาร หรือชื่อโครงการในชื่อสินค้า
7. Abbreviation ใช้ได้เฉพาะที่อยู่ใน **Abbreviation Dictionary** (จะส่งมอบพร้อมไฟล์ Excel)

### เทียบก่อน-หลัง

| เดิม | ใหม่ |
|---|---|
| `Repair Air Blower--Asset & Spare parts--Air Diffuser` | `MACHINE REPAIR - งานซ่อม Air Blower - Air Diffuser Part` |
| `ชุดตรวจ ,Funnel 100 ml (non-sterile)` | `LAB CONSUMABLE - Filtration Funnel - 100 mL Non-Sterile` |
| `MOBIL NUTO H 32 -1/208LT.` | `LUBRICANT - Hydraulic Oil MOBIL NUTO H 32 - 208 L/Drum` |

---

## 2.4 Attribute Schema

### Common Core — ทุกรายการต้องมี (18 field)

| # | Field | ชนิด | บังคับ | ที่มา | หมายเหตุ |
|---|---|---|---|---|---|
| 1 | `Item Number` | Text(11) | ✔ | สร้างใหม่ | ตัวเลข 11 หลัก |
| 2 | `Legacy Item Number` | Text(11) | ✔ | เดิม | รหัส 64xxx — **ห้ามลบทิ้งตลอดไป** |
| 3 | `Product Name` | Text(110) | ✔ | สร้างใหม่ | ตาม naming convention |
| 4 | `Search Name` | Text(60) | ✔ | derive | Noun หลัก + ยี่ห้อ (สำหรับค้นใน D365) |
| 5 | `Product Type` | Enum | ✔ | แก้ไข | `Item` / `Service` |
| 6 | **`Category`** | Text | ✔ | ใหม่ | **ชื่อ Item Group — source of truth ของ report** |
| 7 | **`Category Code`** | Text(3) | ✔ | ใหม่ | 700-710 / 900-908 |
| 8 | **`Sub-Category`** | Text | ✔ | ใหม่ | **ชื่อหมวดย่อย — source of truth ของ report** |
| 9 | **`Sub-Category Code`** | Text(2) | ✔ | ใหม่ | 01-99 |
| 10 | `Scope Owner` | Enum | ✔ | ใหม่ | `SPT` / `GN` — ตรงกับ scope ของ ACM |
| 11 | `Base UoM` | Text | ✔ | derive | หน่วยนับหลัก จาก UoM master |
| 12 | `Purchase UoM` | Text | ✔ | derive | หน่วยที่สั่งซื้อจริง |
| 13 | `Pack Size` | Decimal | ○ | derive | เช่น 208 |
| 14 | `Pack UoM` | Text | ○ | derive | เช่น L |
| 15 | `Conversion to Base` | Decimal | ○ | derive | Purchase UoM → Base UoM |
| 16 | `Lifecycle State` | Enum | ✔ | ใหม่ | `Active` / `Blocked` / `Obsolete` |
| 17 | `Plant / Company` | Text | ✔ | ใหม่ | `CBD` |
| 18 | `Data Quality Flag` | Enum | ✔ | ใหม่ | `Clean` / `Needs Review` / `Merged` |

### Management View — เพิ่มเติมสำหรับ procurement

| Field | บังคับ | หมายเหตุ |
|---|---|---|
| `Spend Category (UNSPSC L2)` | ○ แนะนำ | ไว้เทียบ spend กับ benchmark ภายนอกในอนาคต |
| `Preferred Supplier` | ○ | |
| `Contract Reference` | ○ | |
| `Last Purchase Price` / `Currency` | ○ | ดึงจาก D365 |
| `Sourcing Owner` | ✔ | ผู้รับผิดชอบจัดหา |

### Operations View — เพิ่มเติมตามหมวด

| หมวด | Field เพิ่ม |
|---|---|
| **900 / 901** Spare & Electrical | `Equipment / Machine Linkage`, `Manufacturer Part No.`, `Criticality (A/B/C)`, `Material / Spec` |
| **902** Lab | `Instrument Linkage`, `Grade`, `Shelf Life`, `Storage Condition` |
| **903** Chemical | `Food Contact (Y/N)`, `Food Grade`, `SDS Reference`, `Hazard Class`, `Shelf Life`, `Storage Condition`, `CoA Required (Y/N)` |
| **904 / 905** Construction & Factory Consume | `Material / Spec`, `Dimension`, `Food Contact (Y/N)` |
| **906** General Consume | `Size / Variant` (เช่น ไซส์ยูนิฟอร์ม, ไซส์ถุงมือ) |
| **907** IT | `Warranty Period`, `Asset Tag Required (Y/N)` |
| **7xx** Service | `Service Location`, `Frequency (One-time / Monthly / Annual)`, `Contract Required (Y/N)`, `Certification Required (Y/N)` |

> **หมายเหตุด้าน Food Safety:** CBD เป็นโรงงานเครื่องดื่ม field `Food Contact` / `Food Grade` / `SDS Reference` / `CoA Required` ไม่ใช่ metadata ทางเลือก — เป็นข้อมูลที่ audit FSSC 22000 / GMP ขอดูโดยตรง ควรบังคับกรอกสำหรับหมวด 903 และของที่สัมผัสผลิตภัณฑ์ในหมวด 904/905

---

## 2.5 ตัวอย่างจริง 15 รายการ (รหัสใหม่เป็น illustrative — running จะรันจริงตอนแปลงข้อมูล)

| # | รหัสเดิม | ชื่อเดิม | รหัสใหม่ | ชื่อใหม่ | Category | Sub-Category |
|---|---|---|---|---|---|---|
| 1 | `64SP000218` | ลูกปืน SKF 6001-2RSH | `90001000001` | `BEARING - Ball Bearing SKF - 6001-2RSH` | Spare Parts & Mechanical Parts | Bearing & Power Transmission |
| 2 | `64FQ001445` | สกรูหัวจมดำเกลียวมิล เกรด12.9M4x0.7x10mm | `90003000001` | `FASTENER - Socket Head Cap Screw เหล็กชุบดำ - Grade 12.9 M4x0.7x10 mm` | Spare Parts & Mechanical Parts | Fastener |
| 3 | `64FQ002004` | ข้องอเชื่อม SUS304 90° SCH10 1" | `90004000001` | `PIPE FITTING - Butt Weld Elbow 90° SUS304 - SCH10 1 in` | Spare Parts & Mechanical Parts | Pipe, Fitting & Valve |
| 4 | `64FL000016` | กรองน้ำมันเครื่อง | `90009000001` | `FORKLIFT PART - Engine Oil Filter - รอระบุรุ่นรถ` ⚠️ | Spare Parts & Mechanical Parts | Forklift & Mobile Equipment Part |
| 5 | `64CS000289` | หลอดไฟตู้เทียบสี Philips Master TL-D90 Graphica 18W/965 T8 | `90104000001` | `LIGHTING - Fluorescent Tube Philips Master TL-D90 Graphica - 18 W/965 T8` | Electrical Parts | Lighting |
| 6 | `64LQ000004` | BEAKER LOW FORM 250ML KIMA | `90201000001` | `LABWARE - Beaker Low Form KIMAX - 250 mL` | Lab Instruments | Glassware & Labware |
| 7 | `64CS000365` | MOBIL NUTO H 32 -1/208LT. | `90304000001` | `LUBRICANT - Hydraulic Oil MOBIL NUTO H 32 - 208 L/Drum` | Chemicals (Oil & Gas) | Lubricant & Grease |
| 8 | `64BD000421` | น้ำยาล้างจาน 20 ลิตร | `90303000001` | `CLEANING CHEM - น้ำยาล้างจาน - 20 L/แกลลอน` | Chemicals (Oil & Gas) | Cleaning Chemical |
| 9 | `64FU000005` | LIQUID NITROGEN (REFILL) | `90305000001` | `INDUSTRIAL GAS - Liquid Nitrogen - Refill` | Chemicals (Oil & Gas) | Fuel & Industrial Gas |
| 10 | `64BD000898` | ปูน CPAC Plant 240 KSC | `90401000001` | `CIVIL MATERIAL - คอนกรีตผสมเสร็จ CPAC - 240 ksc` | Construction Materials | Civil & Structural Material |
| 11 | `64OF000201` | ปากกาไวท์บอร์ด สีแดง | `90601000001` | `STATIONERY - ปากกาไวท์บอร์ด - สีแดง` | General Consume | Office Stationery & Paper |
| 12 | `64SF000121` | แว่นครอบตากันสารเคมี Goggle | `90603000001` | `PPE - Safety Goggle กันสารเคมี - Clear Lens` | General Consume | PPE & Safety Equipment |
| 13 | `64IT000004` | SSD SATA KINGSTON A400 (SA400S37/240G) | `90704000001` | `STORAGE - SSD SATA Kingston A400 - 240 GB (SA400S37/240G)` | IT Hardware & Accessories | Storage & Memory |
| 14 | `64SV000543` | งานสอบเทียบ pH meter pH Basic-Bio-Kit | `70201000001` | `CALIBRATION - งานสอบเทียบ pH Meter - Model pH Basic-Bio-Kit` | Calibration & Certification Service | Instrument Calibration |
| 15 | `64MD000004` | ซื้อสื่อออนไลน์-Youtube | `70601000001` | `ONLINE MEDIA - ค่าสื่อโฆษณาออนไลน์ - YouTube` | Marketing Service | Online Media |

**สิ่งที่ตัวอย่างชุดนี้พิสูจน์ให้เห็น:**

- ✅ รหัสใหม่ทุกตัวมีหลัก 4-5 ≥ 01 → **ไม่ชนรหัส ACM/APM/APG แน่นอน**
- ✅ ตัวอย่างที่ 14 แก้ `Product type` จาก Item → Service และย้ายเข้า 7xx ถูกช่อง
- ✅ ตัวอย่างที่ 7 และ 8 อยู่คนละหมวดย่อยแต่ Category เดียวกัน — spend report กลิ้งขึ้นได้ทั้ง 2 ระดับ
- ⚠️ ตัวอย่างที่ 4 (`กรองน้ำมันเครื่อง`) แสดงข้อจำกัดจริง: ชื่อเดิมไม่บอกรุ่นรถ ในขณะที่มี `64FL000216 กรองน้ำมันเครื่อง Toyota 1DZII` อยู่ด้วย → **รายการแบบนี้จะเข้า Needs_Review ไม่เดา**

---

## 2.6 บันทึกการตัดสินใจ (Peter ยืนยันแล้ว 3 ส.ค. 2026)

| # | ประเด็น | คำตัดสิน | ผลต่อการแปลงข้อมูล |
|---|---|---|---|
| 1 | **SVSP 292 รายการ** ปนบริการ + อะไหล่ | ✅ **แตกเป็น 2 รหัส** | 292 รายการเดิม → ประมาณ 584 รหัสใหม่ (1 service ใน 7xx + 1 spare part ใน 9xx) ทั้งคู่จะอ้างกลับไปที่รหัสเดิมเดียวกันใน `Mapping` sheet สถานะ = `แตกรหัส` |
| 2 | **MC 13 + VE 3 รายการ** = สินทรัพย์ | ✅ รับทราบ — ลง `Needs_Review` พร้อมข้อเสนอโอนไป Fixed Asset รอ Accounting | 16 รายการไม่ได้รหัสใหม่ในรอบนี้ แต่ยังอยู่ครบใน `Mapping` |
| 3 | **รหัส 800/803/805 หลุดในไฟล์ ACM** | ✅ ไม่กระทบ CBD non-stock — เดินหน้าต่อ | บันทึกไว้ใน `Summary` เป็น open issue ให้ทีม Stock ทราบ |
| 4 | **Group 908 Marketing ว่างเปล่า** | ✅ เพราะ ACM ยังไม่เคยซื้อของ Marketing | **CBD จะเป็นผู้ใช้รายแรกของ 908** → taxonomy ที่ CBD วางจะกลายเป็นมาตรฐานกลุ่มโดยปริยาย ยิ่งต้องออกแบบให้ดี (ดูเอกสารแนบฉบับที่ 2) |

## 2.7 สิ่งที่ยังเปิดค้างอยู่

| # | คำถาม | ผลกระทบถ้ายังไม่ตอบ |
|---|---|---|
| 5 | **34 รายการ `(ยกเลิก)`** — ยกไป master ใหม่ในสถานะ Blocked หรือไม่ยกเลย? | ผมแนะนำให้ยกไปแบบ Blocked เพื่อรักษา audit trail (จะทำแบบนี้ถ้าไม่แย้ง) |
| 6 | **104 รายการชื่อว่าง/เป็น "."** | ต้องดึงชื่อจริงจากประวัติ PO หรือให้ user ระบุ — ลง `Needs_Review` ทั้งหมด |
| 7 | ยืนยัน **Sub-Category dictionary เป็นมาตรฐานระดับกลุ่ม** กับ MDM ส่วนกลาง | ถ้าไม่ล็อก จะชนกับ ACM/APM/APG ในอนาคต |
| 8 | **Uniform ~140 รายการ** (MD 29 + WF 122 ที่เกี่ยวข้อง) ต้องแยกระหว่างสวัสดิการ (906-04) กับ marketing apparel (908-07) | ต้องใช้กฎ "ใครใส่ เพื่ออะไร" — ที่ตัดสินไม่ได้จะลง `Needs_Review` |

---

## ขั้นตอนถัดไป

**หยุดรออนุมัติที่จุดนี้ตามที่กำหนด**

เมื่อ Peter อนุมัติ ผมจะดำเนินการ:
1. สร้าง UoM master + Abbreviation dictionary
2. แปลงข้อมูลจริงทั้ง 7,700 รายการ
3. ส่งมอบไฟล์ Excel 5 sheet: `Mapping` · `New_Item_Master` · `Duplicates` · `Needs_Review` · `Summary`

**การันตี:** ทุกรายการเดิม 7,700 รายการจะปรากฏใน `Mapping` sheet โดยไม่มีข้อยกเว้น — ค้นจากรหัส 64xxx เจอรหัสใหม่ทันที
