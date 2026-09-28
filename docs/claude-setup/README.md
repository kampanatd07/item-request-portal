# ตั้งค่า Claude Code สำหรับโปรเจกต์นี้

## 1. ย้ายโปรเจกต์ออกจาก OneDrive (ครั้งเดียว)

OneDrive ทำให้ SQLite และ git พัง และ git worktree (ที่ใช้รันหลาย agent ขนานกัน)
จะพังหนักกว่านี้อีก ใช้ `D:\dev` (ไดรฟ์ C พื้นที่ใกล้เต็ม) — จะไดรฟ์ไหนก็ได้
ขอแค่**ไม่อยู่ใต้โฟลเดอร์ OneDrive**

```powershell
mkdir D:\dev
robocopy "D:\OneDrive - Carabao Tawandang Co.,Ltd\Kmapanat\Project - Plant\2026 - Item Createter\Rule of Item\item-request-portal" D:\dev\item-request-portal /E /XD .venv __pycache__ .pytest_cache /XF dev.db dev.db-journal
cd D:\dev\item-request-portal
```

แล้วสร้าง venv ใหม่ (venv ย้ายที่ไม่ได้) — ตั้ง pip cache ไว้ที่ D ด้วย
ไม่งั้น pip จะไปเก็บไฟล์ดาวน์โหลดไว้ที่ C:
```powershell
$env:PIP_CACHE_DIR = "D:\dev\.pip-cache"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

ใช้ Python 3.13 ที่ติดตั้งจาก python.org (`python --version` ต้องขึ้น 3.13.x)
venv อยู่ใน `D:\dev\item-request-portal\.venv` (~200 MB) ส่วนตัว Python เองอยู่ที่ C: ไม่ต้องย้าย

เมื่อย้ายเสร็จและรันได้แล้ว ลบ `.venv` ในโฟลเดอร์ OneDrive ทิ้งได้ (ประหยัดพื้นที่ sync)
โฟลเดอร์ OneDrive เก็บไว้เป็นแค่ backup — **แก้งานที่ `D:\dev` ที่เดียว** ไม่งั้นจะมีสองชุดที่ไม่ตรงกัน

## 2. ขึ้น GitHub (private)

สร้าง repo เปล่าบน GitHub ชื่อ `item-request-portal` แบบ **Private** แล้ว:
```powershell
git remote add origin https://github.com/<username>/item-request-portal.git
git push -u origin master
```

## 3. ความรู้ 3 ชั้น

| ชั้น | อยู่ที่ไหน | ใช้กับ |
|---|---|---|
| Skills ของ Matt Pocock (วิธีทำงาน) | plugin `mattpocock-skills` ระดับเครื่อง | ทุกโปรเจกต์ |
| `carabao-item-master` (มาตรฐาน item master กลุ่ม + กับดักภาษาไทย) | `%USERPROFILE%\.claude\skills\` — ต้นฉบับอยู่ที่ `docs/claude-setup/skills/` | ทุกงานที่แตะรหัส/ชื่อ/หมวด/UoM/ข้อความไทย |
| ภาษาและสถานะของโปรเจกต์นี้ | `CONTEXT.md`, `CLAUDE.md`, `docs/HANDOFF.md` | โปรเจกต์นี้เท่านั้น |

ไม่แก้ skill ของ Matt — "สอน" โปรเจกต์ผ่านไฟล์ใน repo ที่ skill ของเขาอ่านเองอยู่แล้ว

## 4. ติดตั้ง (ครั้งเดียว)

**4.1 Skill ของ Matt** — เปิด Claude Code แล้วพิมพ์:
```
/plugin install mattpocock-skills
```

**4.2 Skill มาตรฐานกลุ่ม** — ใน PowerShell ที่ `D:\dev\item-request-portal`:
```powershell
mkdir $HOME\.claude\skills -Force
Copy-Item docs\claude-setup\skills\carabao-item-master $HOME\.claude\skills\ -Recurse -Force
```
เมื่อแก้มาตรฐาน ให้แก้ต้นฉบับใน repo แล้วรันคำสั่ง Copy-Item ซ้ำ

**4.3 ตั้งค่า repo** — เปิด Claude Code ที่ `D:\dev\item-request-portal` แล้วพิมพ์
`/setup-matt-pocock-skills` ตอบดังนี้:
- Issue tracker → **local files** ที่ `docs/stories/`
- Triage labels → ใช้ค่าตั้งต้นของเขา
- ที่เก็บเอกสาร → single-context (`CONTEXT.md` ที่ root) การตัดสินใจเก็บที่
  `docs/decisions.md` ที่เดียว **ไม่มี `docs/adr/`**

ผลลัพธ์อยู่ใน `docs/agents/` และหัวข้อ `## Agent skills` ใน `CLAUDE.md`

**4.4 ทวนภาษาโปรเจกต์** — พิมพ์ `/grill-with-docs` แล้วบอกว่า
"ทวน CONTEXT.md กับผม" มีร่างให้แล้ว คุณแค่ยืนยันหรือแก้คำที่ไม่ตรงกับที่ทีมเรียกจริง

## 5. Workflow ต่อ 1 story

| ขั้น | พิมพ์ | ได้อะไร |
|---|---|---|
| 1. ให้ชัดก่อน | `/grill-with-docs` + บอกว่าจะทำ STORY-001 | ตอบคำถามจนไม่เหลือจุดคลุมเครือ, CONTEXT.md อัปเดต |
| 2. เป็นสเปค | `/to-spec` | สเปคจากสิ่งที่คุยกัน |
| 3. แตกงาน | `/to-tickets` | ticket ย่อยที่รู้ลำดับว่าอะไรต้องทำก่อน |
| 4. ลงมือ | `/implement` | ทำด้วย `/tdd` (test fail ก่อนเสมอ) แล้วปิดด้วย `/code-review` |
| 5. ตรวจมาตรฐานกลุ่ม | "ตรวจ diff ด้วย carabao-item-master" | รายการที่ขัดมาตรฐาน พร้อม file:line |
| 6. ตัดสิน | Peter อ่าน diff แล้ว merge | — |

ทำบน branch `story/NNN-short-name` เสมอ **Peter เป็นคนตัดสิน merge ทุกครั้ง**

ไม่แน่ใจว่าควรใช้ skill ไหน → พิมพ์ `/ask-matt`

## 6. รันหลาย story พร้อมกัน

STORY-002, 003, 004 แตะไฟล์คนละส่วน ทำขนานกันได้ ให้แต่ละตัวอยู่คนละ worktree:

```powershell
git worktree add ..\irp-story-003 -b story/003-uom-standard
git worktree add ..\irp-story-004 -b story/004-item-attributes
```

เปิด Claude Code แยกหน้าต่างในแต่ละโฟลเดอร์ แล้วทำ workflow ข้อ 5 ของ story นั้น

**ข้อควรระวัง:** ทั้ง 003 และ 004 สร้าง migration — ถ้า merge ทั้งคู่จะได้ Alembic head
สองตัว ให้ merge ทีละตัว แล้วตัวที่สองต้อง rebase และสร้าง migration ใหม่ต่อจากตัวแรก

## 7. เริ่ม session ใหม่ทุกครั้ง

พิมพ์: `อ่าน docs/HANDOFF.md แล้วสรุปสถานะ 3 บรรทัด`
ถ้าข้อมูลในแชทขัดกับไฟล์ ให้เชื่อไฟล์
