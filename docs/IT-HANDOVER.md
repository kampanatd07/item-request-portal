# IT Handover — Item Request Portal / ส่งมอบงานให้ทีม IT

> ร่าง / Draft: 2026-11-03 · ส่งมอบโดย / Handed over by: Peter (Procurement
> Strategy), last day 2026-11-13 · ผู้รับ / Received by: ทีม IT / IT team
>
> ชื่อแทน / Placeholders: `[IT-OWNER]`, `[IT-DEVELOPER]`, `[BUSINESS-OWNER]`
> (ตาราง C1 / table C1). กรอกชื่อจริงตอนลงชื่อรับมอบ / fill in at sign-off.
>
> ไฟล์นี้คือจุดเริ่มอ่าน รายละเอียดอยู่ใน `docs/HANDOFF.md` ถ้าสถานะในสองไฟล์ขัดกัน
> ให้เชื่อ HANDOFF / This file is the entry point; details live in
> `docs/HANDOFF.md`. If the two disagree on status, HANDOFF wins.
>
> ส่วน A (ไทย) และส่วน B (English) มีเนื้อหาเดียวกัน แก้ส่วนหนึ่งต้องแก้อีกส่วนด้วย
> / Parts A (Thai) and B (English) say the same thing: edit both together.

---

## ส่วน A — ภาษาไทย

### A1. ระบบนี้คืออะไร
เว็บแอปให้พนักงาน 4 โรงงาน (CBD, APM, APG, ACM) ขอเปิด item จัดซื้อใหม่ประเภท
non-stock และ service ระบบตรวจรายการซ้ำ แนะนำหมวด ประกอบชื่อตามมาตรฐานกลุ่ม
ออกรหัสกลาง 11 หลักจาก running register และ export ไฟล์ import ของ AX/D365
แยกตามโรงงาน **ระบบไม่เขียนข้อมูลเข้า AX/D365 โดยตรง** คนนำไฟล์ไป import เอง
ใช้แทนขั้นตอนเดิม: Microsoft Forms → Procurement ตรวจเอง → พิมพ์เข้า AX → อีเมลตอบ

ผู้ใช้: ผู้ขอจากโรงงาน, Procurement 1–2 คน, Administrator
เทคโนโลยี: Python 3.12, FastAPI, SQLAlchemy + Alembic, PostgreSQL 16 (production)
/ SQLite (เครื่องพัฒนา), HTMX + Jinja2, Docker container เดียว 1 worker,
อีเมลผ่าน Microsoft Graph, Anthropic API เป็นตัวเลือกเสริมสำหรับแนะนำชื่อค้นหา
รายละเอียดสถาปัตยกรรม: `docs/architecture.md`

### A2. สถานะวันนี้ (2026-11-11)
- โค้ดก่อน deploy เสร็จครบ เทสต์ 992 ตัวบน CI (ตัวเลขที่อ่านแล้วล่าสุดอยู่ใน HANDOFF §2)
- หน้าเว็บยกเครื่องใหม่ทั้งหมด (STORY-018, 2026-11-09): เมนูด้านซ้าย ฟอร์มแบบนำทาง
  คิวแบบแท็บ คำอธิบายสถานะ และหน้า `/help` สำหรับผู้ใช้
- **ยังไม่ได้ deploy และยังไม่เปิดให้โรงงานใช้** ตอนนี้รันอยู่บนเครื่องของ Peter เท่านั้น
- ลำดับก่อนเปิดใช้ (HANDOFF §2):
  1. Cutover Plan เฟส 1: โหลด master กลาง `Central_v5_with_DCM` (13,400 รหัส) เข้า D365
  2. เลือกเส้นทาง delta ของ item ที่โรงงานเปิดในระบบเดิมหลัง 2026-08-07:
     A = ผ่านพอร์ทัล (พอร์ทัลออกเลขเอง) หรือ B = ผ่าน group pipeline แล้ว
     re-sync register (STORY-005)
  3. กำหนดวัน cut-over ที่หลังจากนั้นออกรหัสกลางได้จากพอร์ทัลที่เดียว
  4. Deploy (STORY-006 part B): hosting, PostgreSQL, อีเมลจริง, backup/restore
  5. เปิดให้โรงงานใช้
- **ห้ามรัน group pipeline ใหม่ทั้งชุดหลังรหัส v5 ถูกใช้แล้ว** pipeline ออกรหัสใหม่
  ทั้งชุด รหัสเดิมอาจเลื่อน delta ต้องคงรหัส v5 ทุกตัว

### A3. บัญชีและ secret ที่ต้องรับช่วง
ดูตาราง C2 ไฟล์นี้ไม่มีค่า secret ใดๆ ตัวแปรทั้งหมดอธิบายไว้ใน `.env.example`
ส่วนใหญ่ยังไม่ได้สร้าง เพราะยังไม่ได้ deploy

### A4. ข้อมูลที่อยู่นอก repo
ดูตาราง C3 ไฟล์ข้อมูลกลุ่มอยู่ใน OneDrive ของ Peter ซึ่งจะถูกลบหลังปิดบัญชี
**ต้องย้ายไปที่ของทีมก่อน 2026-11-13** ไฟล์ `Central_v5_with_DCM.xlsx` เข้ารหัส IRM:
ต้องให้สิทธิ์ทีม IT หรือทำสำเนาที่ไม่เข้ารหัสก่อน Peter ออก ไม่อย่างนั้นอาจไม่มีใครเปิดได้

### A5. โอน repository
ตอนนี้โค้ดอยู่บน GitHub ส่วนตัวของ Peter (`kampanatd07/item-request-portal`, private)
- **ถ้าบริษัทใช้ GitHub:** Settings → General → Danger Zone → Transfer ownership
  ไปที่ org ของบริษัท `(fill in)` ประวัติ commit, CI และ issues ย้ายไปครบ ลิงก์เก่า
  redirect ให้เอง
- **ถ้าใช้ที่อื่น (Azure DevOps, GitLab ฯลฯ):** สร้าง repo ว่างที่ปลายทาง แล้ว
  `git clone --mirror <ที่เดิม>` → `cd item-request-portal.git` →
  `git push --mirror <ที่ใหม่>` ได้ประวัติและ branch ครบ แต่ต้องสร้าง CI ใหม่
  เพราะ `.github/workflows/ci.yml` ใช้ได้กับ GitHub เท่านั้น สิ่งที่ CI ต้องทำ:
  PostgreSQL 16, migrate + seed บนฐานว่าง, `alembic check`, รัน pytest ทั้งชุดโดยตั้ง
  `TEST_POSTGRES_URL`
- **หลังโอนทั้งสองแบบ:** ยืนยันว่า `[IT-OWNER]` เป็น admin, รัน CI หนึ่งรอบต้องได้
  **992 passed, 0 skipped**, ถอนสิทธิ์บัญชีส่วนตัวของ Peter, ตั้ง branch protection
  ถ้าแพลนรองรับ (ตอนนี้ไม่มี CI แดงจึงไม่บล็อกการ merge)

### A6. ทำงานต่อด้วย Claude Code
- ติดตั้งตาม `docs/claude-setup/README.md` §4 (plugin `mattpocock-skills` และ
  skill `carabao-item-master`)
- เปิด Claude Code ที่โฟลเดอร์ repo แล้ว `CLAUDE.md` จะโหลดเอง ในนั้นมีกติกาการทำงาน
  ทั้งหมด (ย้ายมาจาก memory บนเครื่อง Peter เมื่อ 2026-11-03)
- คำสั่งแรกของ session: `อ่าน docs/IT-HANDOVER.md, docs/HANDOFF.md และ docs/decisions.md แล้วสรุปสถานะ 3 บรรทัด`
- งานหน้าเว็บ: ใช้ skill `/impeccable` ซึ่งอ่าน `PRODUCT.md` ก่อนทุกครั้ง ระบบหน้าตาทั้งหมดอยู่ใน
  `app/templates/base.html` ห้ามใส่สีหรือขนาดตรงๆ ในแต่ละหน้า
- ห้ามทำงานใน OneDrive: SQLite และ git พัง (HANDOFF §6.6)

### A7. ความเสี่ยงที่รู้อยู่
1. ไฟล์ export **ยังไม่เคยทดสอบ import เข้า AX/D365 จริง**
2. snapshot ที่ใช้ตรวจซ้ำคือ `Central_v4` ซึ่งไม่มีรายการ DCM จึงตรวจไม่เจอ DCM
3. register นำหน้า v4 ใน 5 หมวดย่อย: ยืนยันแล้ว 2 (DCM ใน v5) อีก 3 ยังไม่ได้ตรวจ (STORY-005)
4. taxonomy: ไฟล์ v4 มี 105 หมวดย่อย แต่พอร์ทัลมี 130 ยังไม่ได้ยืนยันว่าฉบับไหนใช้จริง
5. รัน pipeline ใหม่ทั้งชุด = รหัสเลื่อน (A2)
6. อีเมลยังไม่เคยส่งจริง ทดสอบกับตัวจำลองเท่านั้น
7. backup/restore ยังไม่เคยทดสอบ เพราะยังไม่ได้ deploy
8. ค่า `FORWARDED_ALLOW_IPS` ที่ผิดตรวจอัตโนมัติไม่ได้ ต้องเช็กหลัง deploy ว่า 2 เครื่องนับเป็น 2 IP
9. STORY-016: reset รหัสผ่านพร้อมกันสองทาง session เก่าอาจรอด ทำเป็นงานแรกหลัง go-live
10. ไม่มี branch protection: CI แดงไม่บล็อก merge ต้องดูผล CI เองทุกครั้ง

### A8. เรื่องที่ต้องมีคนตัดสินใจ
อยู่ใน HANDOFF §7 แต่ละข้อมีช่อง "ใครรับ" ส่วนใหญ่เป็นของ `[BUSINESS-OWNER]`
(taxonomy, รหัส, เส้นทาง delta A/B, วัน cut-over) และ `[IT-OWNER]` (ค่า Graph,
นโยบาย host ภายนอก, วันหมดอายุ secret)

---

## Part B — English

### B1. What the system is
A web app where staff at the 4 plants (CBD, APM, APG, ACM) request new
non-stock and service purchase items. It checks for duplicates, suggests a
category, composes the group-standard name, issues a central 11-digit code
from the running register, and exports AX/D365 import files per plant.
**It never writes to AX/D365 directly**: a person imports the files. It
replaces Microsoft Forms → Procurement checks by hand → types into AX → emails back.

Users: plant requesters, Procurement (1–2 people), Administrators.
Tech: Python 3.12, FastAPI, SQLAlchemy + Alembic, PostgreSQL 16 (production)
/ SQLite (development), HTMX + Jinja2, one Docker container with one worker,
email through Microsoft Graph, optional Anthropic API for search-name
suggestions. Architecture: `docs/architecture.md`.

### B2. Status today (2026-11-11)
- All code before deploy is done; 992 tests on CI (the last numbers read
  are in HANDOFF §2).
- The UI was overhauled (STORY-018, 2026-11-09): sidebar, guided form,
  queue tabs, status explanations and a `/help` page for users.
- **Not deployed and not open to the plants.** It runs on Peter's machine only.
- Order before opening (HANDOFF §2):
  1. Cutover Plan phase 1: load the central master `Central_v5_with_DCM`
     (13,400 codes) into D365.
  2. Pick the delta route for items the plants opened in the old system
     after 2026-08-07: A = through the portal (it issues the numbers), or
     B = through the group pipeline, then re-sync the register (STORY-005).
  3. Set the cut-over date after which only the portal issues central codes.
  4. Deploy (STORY-006 part B): hosting, PostgreSQL, real email, backup/restore.
  5. Open to the plants.
- **Never re-run the whole group pipeline once v5 codes are in use.** It
  issues every code afresh, so existing codes may shift. A delta must keep
  every v5 code.

### B3. Accounts and secrets to take over
See table C2. No secret values are in this file; every variable is
explained in `.env.example`. Most do not exist yet, because nothing is deployed.

### B4. Data outside the repository
See table C3. The group data files are in Peter's OneDrive, which is
deleted when his account closes: **move them to a team location before
2026-11-13.** `Central_v5_with_DCM.xlsx` is IRM-encrypted: grant the IT team
rights or make an unencrypted copy before Peter leaves, or nobody may be
able to open it.

### B5. Moving the repository
The code is on Peter's personal GitHub (`kampanatd07/item-request-portal`, private).
- **If the company uses GitHub:** Settings → General → Danger Zone →
  Transfer ownership to the company org `(fill in)`. History, CI and issues
  move; the old URL redirects.
- **Any other host (Azure DevOps, GitLab…):** create an empty repo there,
  then `git clone --mirror <old>` → `cd item-request-portal.git` →
  `git push --mirror <new>`. History and branches move; CI must be rebuilt,
  since `.github/workflows/ci.yml` is GitHub-only. What CI must do:
  PostgreSQL 16, migrate + seed on an empty database, `alembic check`, the
  whole pytest suite with `TEST_POSTGRES_URL` set.
- **After either:** confirm `[IT-OWNER]` is admin, run CI once: **992
  passed, 0 skipped**; remove Peter's personal account; turn on branch
  protection if the plan allows (today a red CI does not block a merge).

### B6. Continuing with Claude Code
- Install per `docs/claude-setup/README.md` §4 (plugin `mattpocock-skills`,
  skill `carabao-item-master`).
- Open Claude Code in the repo folder: `CLAUDE.md` loads by itself and holds
  every working rule (moved from the memory on Peter's machine, 2026-11-03).
- First prompt of a session: `อ่าน docs/IT-HANDOVER.md, docs/HANDOFF.md และ docs/decisions.md แล้วสรุปสถานะ 3 บรรทัด`
  ("read the three and summarise the status in 3 lines").
- UI work: use the `/impeccable` skill, which reads `PRODUCT.md` first. The
  whole design system is in `app/templates/base.html`: pages do not
  hardcode colors or sizes.
- Never work inside OneDrive: it breaks SQLite and git (HANDOFF §6.6).

### B7. Known risks
1. The export files have **never been imported into real AX/D365**.
2. The duplicate check's snapshot is `Central_v4`, which has no DCM items,
   so DCM duplicates are not found.
3. The register is ahead of v4 in 5 sub-categories: 2 verified (DCM in v5),
   3 not yet checked (STORY-005).
4. Taxonomy: the v4 file has 105 sub-categories, the portal 130; which is
   current is not confirmed.
5. Re-running the whole pipeline shifts codes (B2).
6. Email has never been sent for real (tested with a fake transport only).
7. Backup/restore never tested (nothing deployed).
8. A wrong `FORWARDED_ALLOW_IPS` cannot be detected automatically: after
   deploy, check that two machines count as two IPs.
9. STORY-016: two simultaneous password resets can let old sessions
   survive; first story after go-live.
10. No branch protection: a red CI does not block a merge; read CI every time.

### B8. Decisions someone must make
Listed in HANDOFF §7, each with a "who" column. Most belong to
`[BUSINESS-OWNER]` (taxonomy, codes, delta route A/B, cut-over date) or
`[IT-OWNER]` (Graph values, external hosting policy, secret expiry).

---

## ส่วน C / Part C — ตาราง / Tables

### C1. บทบาท / Roles

| Placeholder | หน้าที่ / Responsibilities | ชื่อ / Name |
|---|---|---|
| `[IT-OWNER]` | repo, hosting, secret, ค่า Graph, อนุมัติ merge / repo, hosting, secrets, Graph app, approves merges | (fill in) |
| `[IT-DEVELOPER]` | แก้ระบบกับ Claude Code ตาม `CLAUDE.md` / day-to-day changes with Claude Code | (fill in) |
| `[BUSINESS-OWNER]` | Procurement: taxonomy, รหัส, register, เส้นทาง delta, วัน cut-over, ตรวจผลในเบราว์เซอร์ / taxonomy, codes, register, delta route, cut-over date, browser checks | (fill in) |

### C2. บัญชีและ secret / Accounts and secrets

| รายการ / Item | ตอนนี้ / Now | ต้องทำ / Action | ใคร / Who |
|---|---|---|---|
| Git repository | GitHub ส่วนตัว / personal: `kampanatd07/item-request-portal` | โอน / transfer (A5/B5) | Peter → `[IT-OWNER]` |
| CI (GitHub Actions, `ci.yml`, ไม่ใช้ secret / no secrets) | ใน repo เดิม / in that repo | ย้ายตาม repo หรือสร้างใหม่ / moves with it, or rebuild | `[IT-OWNER]` |
| Hosting + PostgreSQL | ยังไม่สร้าง / not created | เลือกหลังได้คำตอบนโยบาย host ภายนอก (`decisions.md` 2026-07-24) / choose after the hosting-policy answer | `[IT-OWNER]` |
| Entra ID App Registration: `Mail.Send` (application) + admin consent + Application Access Policy | ยังไม่สร้าง / not created | สร้างตาม `.env.example` / create | `[IT-OWNER]` |
| Client secret ของ app นั้น / of that app | ยังไม่สร้าง / not created | จดวันหมดอายุใน HANDOFF §7 / record expiry in HANDOFF §7 | `[IT-OWNER]` |
| Shared mailbox ผู้ส่ง / sender (e.g. `item-portal@carabao.co.th`) + mailbox Procurement สำหรับ Reply-To | ยังไม่สร้าง / not created | สร้าง / create | `[IT-OWNER]` + `[BUSINESS-OWNER]` |
| `SECRET_KEY` | ยังไม่สร้าง / not created | สร้างตอน deploy (`.env.example`) / generate at deploy | `[IT-OWNER]` |
| `ANTHROPIC_API_KEY` (optional) | (fill in: ใช้อยู่ไหม คีย์ของใคร / in use? whose key?) | ใช้คีย์บริษัทหรือเว้นว่าง / company key or leave empty | `[IT-OWNER]` |
| Administrator คนแรกบน production / first production Administrator | ยังไม่มี / none | `python -m app.create_admin` หลัง deploy / after deploy | `[IT-OWNER]` |
| Claude Code ของทีม / for the team | ไลเซนส์ของ IT / IT's own licence | ติดตั้งตาม / install per `docs/claude-setup/README.md` | `[IT-DEVELOPER]` |

### C3. ข้อมูลนอก repo / Data outside the repository

ไฟล์ทั้งหมดย้ายไปที่เดียว โครงสร้างโฟลเดอร์คงเดิม (ตัดสิน 2026-11-06) / Every
file moves to one place, keeping the folder structure (decided 2026-11-06):

- **เดิม / Old (OneDrive ของ Peter, ถูกลบหลังปิดบัญชี / deleted when his account closes):**
  `https://carabao-my.sharepoint.com/personal/kampanat_dae_carabao_co_th/Documents/Kmapanat/Project - Plant/2026 - Item Createter/`
- **ใหม่ / New (SharePoint ของทีม / team site):**
  `https://carabao.sharepoint.com/sites/PurchaseWFH/Shared Documents/General/15. Procurement Strategy/15_Handover_Peter_Kampanat/2026 - Item Createter/`

คอลัมน์ path ด้านล่างนับจากโฟลเดอร์ `2026 - Item Createter/` ซึ่งใช้ได้ทั้งที่เดิมและที่ใหม่
ช่องที่ยังเป็น "(fill in)" คือไฟล์ที่ยังหา path ไม่เจอ: Peter ยืนยัน
/ The path column is relative to `2026 - Item Createter/`, the same under the
old and the new root. "(fill in)": path not found yet, Peter to confirm.

| ไฟล์ / File | คืออะไร / What | path ใต้ / under `2026 - Item Createter/` |
|---|---|---|
| `Handover 2026-11\` (รวม / incl. `04-pipeline-master-กลาง.md`) | ส่งมอบฝั่งกลุ่ม, เส้นทาง delta A/B / group handover, delta routes | `Rule of Item/Handover 2026-11/` |
| `Carabao_Group_Item_Master_Central_v4.xlsx` | master ที่ใช้เป็น snapshot (ไม่มี DCM) / used as the snapshot (no DCM) | `hand-off from other device/Carabao/2026/2026 - Item Creator/` |
| `Carabao_Group_Item_Master_Central_v5_with_DCM.xlsx` (IRM) | master สุดท้าย 13,400 รหัส / final master, 13,400 codes; **ให้สิทธิ์ IRM กับ IT / grant IT IRM rights** | `hand-off from other device/Carabao/2026/2026 - Item Creator/` |
| สำเนา v5 ไม่เข้ารหัส / unencrypted v5 copy | ยังไม่มี; ต้องใช้กับ snapshot และตรวจ 3 หมวดย่อย / does not exist yet; needed for the snapshot and the 3 sub-categories | (fill in) |
| `Carabao_Item_Master_Running_Number_Register_v1.xlsx` | ต้นทางของ register (อยู่ใน `app/data/running_register.json` แล้ว) / register seed source (already in the repo) | `hand-off from other device/Carabao/2026/2026 - Item Creator/` |
| `Decision_Sheet_v2_corrected` | D1–D4 ใช้แล้ว 2026-08-06 / applied | (fill in) |
| group pipeline (`_pipeline\`, `docs/group-standard/GROUP_HANDOVER.md` §5) | สร้าง master; ห้ามรันใหม่ทั้งชุด / builds the master; never re-run whole | (fill in) |
| export item master เดิม / legacy item master exports: `All Item (CBD).xlsx` (CBD); D365 (fill in) | snapshot ตรวจซ้ำ / duplicate-check snapshot | `hand-off from other device/Carabao/2026/2026 - Item Creator/` (CBD) |
| `dev.db` บนเครื่อง Peter / on Peter's machine | ข้อมูลทดสอบ / test data | **ไม่ต้องส่งมอบ ห้ามย้ายเข้า production / do not hand over, never move to production** |

---

## ส่วน D / Part D — Checklist รับมอบ / Handover checklist

ก่อน Peter ออก / Before Peter leaves (2026-11-13):
- [ ] โอน repo แล้ว และ `[IT-OWNER]` เป็น admin / repo transferred, `[IT-OWNER]` is admin
- [ ] ย้ายไฟล์ตาราง C3 แล้ว กรอกช่องที่ใหม่ครบ / C3 files moved, new locations filled in
- [ ] สิทธิ์ IRM ของ v5 ให้ IT หรือมีสำเนาไม่เข้ารหัส / IT has v5 IRM rights or an unencrypted copy
- [ ] ทดลอง import เข้า AX/D365 แล้ว หรือส่งต่อเป็นงานค้างพร้อมไฟล์ตัวอย่าง (HANDOFF §7) / AX/D365 test import done, or handed on with sample files
- [ ] ส่งตัวอย่าง D365 export ที่มีคอลัมน์ company แล้ว (STORY-012) / D365 sample export sent
- [ ] กรอกชื่อในตาราง C1 / names filled in C1
- [ ] กรอกสถานะ `ANTHROPIC_API_KEY` ในตาราง C2 / `ANTHROPIC_API_KEY` status filled in C2
- [ ] ประชุม walk-through กับ IT: รันในเครื่อง ส่งคำขอ 1 รายการจนได้รหัสและไฟล์ export / walk-through with IT: run locally, one request through to a code and an export file

ทีม IT ตอนรับมอบ / IT team on receipt:
- [ ] clone และรันในเครื่องตาม HANDOFF §4 เปิด http://localhost:8000 ได้ / clone and run per HANDOFF §4
- [ ] `pytest` ในเครื่อง: 953 passed, 37 skipped (ไม่มี PostgreSQL) / local pytest: 953 passed, 37 skipped (no PostgreSQL)
- [ ] CI ที่ที่ใหม่: 992 passed, 0 skipped / CI at the new home: 992 passed, 0 skipped
- [ ] ติดตั้ง Claude Code; สรุปสถานะ session แรกตรงกับ HANDOFF §2 / Claude Code set up; its first summary matches HANDOFF §2
- [ ] อ่านความเสี่ยง A7/B7 แล้ว / risks A7/B7 read

| | ชื่อ / Name | วันที่ / Date | ลงชื่อ / Signature |
|---|---|---|---|
| ส่งมอบ / Handed over by | Peter | | |
| รับมอบ / Received by | `[IT-OWNER]` | | |
