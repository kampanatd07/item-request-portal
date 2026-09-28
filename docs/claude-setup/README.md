# ตั้งค่า Claude Code สำหรับโปรเจกต์นี้

## 1. ย้ายโปรเจกต์ออกจาก OneDrive (ครั้งเดียว)

OneDrive ทำให้ SQLite และ git พัง และ git worktree (ที่ใช้รันหลาย agent ขนานกัน)
จะพังหนักกว่านี้อีก

```powershell
mkdir C:\dev
robocopy "D:\OneDrive - Carabao Tawandang Co.,Ltd\Kmapanat\Project - Plant\2026 - Item Createter\Rule of Item\item-request-portal" C:\dev\item-request-portal /E /XD .venv __pycache__ .pytest_cache /XF dev.db dev.db-journal
cd C:\dev\item-request-portal
```

แล้วสร้าง venv ใหม่ (venv ย้ายที่ไม่ได้):
```powershell
& "C:\Users\kampanat.dae\AppData\Local\anaconda3\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. ขึ้น GitHub (private)

สร้าง repo เปล่าบน GitHub ชื่อ `item-request-portal` แบบ **Private** แล้ว:
```powershell
git remote add origin https://github.com/<username>/item-request-portal.git
git push -u origin master
```

## 3. ติดตั้ง agent

```powershell
mkdir .claude\agents -Force
copy docs\claude-setup\agents\*.md .claude\agents\
```

ได้ agent 4 ตัว:

| Agent | ทำอะไร | แก้โค้ดได้? |
|---|---|---|
| `architect` | อ่าน story แล้วเขียนแผนลงในไฟล์ story | ไม่ (แก้ได้แค่ไฟล์ story) |
| `developer` | ทำตามแผนแบบ TDD — test ต้อง fail ก่อนเขียนโค้ด | ได้ |
| `reviewer` | ตรวจ diff เทียบ acceptance criteria | ไม่ |
| `item-master-steward` | ตรวจว่าไม่ขัดมาตรฐานกลุ่ม + กับดักภาษาไทย | ไม่ |

## 4. (แนะนำ) ติดตั้ง skills ของ Matt Pocock

ดูวิธีติดตั้งล่าสุดที่ repo `mattpocock/skills` บน GitHub ตัวที่ใช้บ่อยกับโปรเจกต์นี้:
- `/grill-me` — ให้ Claude สัมภาษณ์เราจนสเปคชัด ก่อนเขียน story ใหม่
- `/tdd` — บังคับ red-green-refactor

## 5. Workflow ต่อ 1 story

เปิด Claude Code ในโฟลเดอร์โปรเจกต์ แล้วพิมพ์ทีละขั้น:

```
1. ให้ architect วางแผน STORY-001
      → อ่านแผนในไฟล์ story ถ้าไม่โอเคบอกให้แก้
2. ให้ developer ทำ STORY-001
      → ทำบน branch story/001-auth-roles
3. ให้ reviewer และ item-master-steward ตรวจ STORY-001
      → อ่าน section Review ท้ายไฟล์ story
4. Peter ตัดสิน merge
```

**Peter เป็นคนตัดสิน merge ทุกครั้ง** agent ไม่ merge เอง

## 6. รันหลาย story พร้อมกัน

STORY-002, 003, 004 แตะไฟล์คนละส่วน ทำขนานกันได้ ให้แต่ละตัวอยู่คนละ worktree:

```powershell
git worktree add ..\irp-story-003 -b story/003-uom-standard
git worktree add ..\irp-story-004 -b story/004-item-attributes
```

เปิด Claude Code แยกหน้าต่างในแต่ละโฟลเดอร์ แล้วสั่ง developer ทำ story ของโฟลเดอร์นั้น

**ข้อควรระวัง:** ทั้ง 003 และ 004 สร้าง migration — ถ้า merge ทั้งคู่จะได้ Alembic head
สองตัว ให้ merge ทีละตัว แล้วตัวที่สองต้อง rebase และสร้าง migration ใหม่ต่อจากตัวแรก

## 7. เริ่ม session ใหม่ทุกครั้ง

พิมพ์: `อ่าน docs/HANDOFF.md แล้วสรุปสถานะ 3 บรรทัด`
ถ้าข้อมูลในแชทขัดกับไฟล์ ให้เชื่อไฟล์
