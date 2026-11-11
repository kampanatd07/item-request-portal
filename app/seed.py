"""Seed reference data: factories, code systems, and rule config.

Extracted from the verified rule documents (docs/rules/*.md). Idempotent:
safe to run repeatedly — inserts only what is missing, never deletes.
Run: python -m app.seed
"""

import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal

DATA_DIR = Path(__file__).parent / "data"


def _load_json(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


from app.models import (
    CodeGroup,
    CodeSystem,
    Factory,
    FactoryCodeSystem,
    GroupExportMap,
    MailDomain,
    ProcurementCategory,
    RunningRegister,
    SearchTerm,
    Uom,
)
from app.services.naming import MAX_CATEGORY_LEN, clean_part
from app.services.thai_labels import HINT_TH_MAX, NAME_TH_MAX, LabelError, clean_label


class SeedError(Exception):
    """Reference data that must not be loaded; a Thai message for the console."""


def check_taxonomy(rows: list[dict]) -> None:
    """Every central Sub-Category needs a Name Prefix of at most 16
    characters: the group standard gives every Item Name a CATEGORY part and
    caps it at 16. Name Prefixes come only from taxonomy.json, so this is
    enforced here, on the prefix as a name would carry it (cleaned), before
    anything is written (STORY-013)."""
    problems = []
    for r in rows:
        cleaned = clean_part(r.get("prefix"))
        n = len(cleaned)
        if n == 0:
            problems.append(f"  {r['group']}-{r['sub']}: Name Prefix ว่าง")
        elif cleaned != (r.get("prefix") or "").strip():
            # Names would carry the cleaned form, not what the file says.
            problems.append(f"  {r['group']}-{r['sub']}: '{r['prefix']}' มีอักขระที่ใช้ในชื่อ"
                            f"ไม่ได้ (ระบบจะเขียนเป็น '{cleaned}')")
        elif n > MAX_CATEGORY_LEN:
            problems.append(f"  {r['group']}-{r['sub']}: '{r['prefix']}' ({n} ตัวอักษร "
                            f"เกิน {MAX_CATEGORY_LEN})")
    if problems:
        lines = "\n".join(problems)
        raise SeedError(
            f"Name Prefix ใน app/data/taxonomy.json ใช้ไม่ได้ (มาตรฐาน: ทุกชื่อต้องมี "
            f"CATEGORY ยาวไม่เกิน {MAX_CATEGORY_LEN} ตัวอักษร):\n{lines}\n"
            "แก้ไฟล์แล้วรัน seed ใหม่ — ยังไม่ได้เขียนอะไรลงฐานข้อมูล"
        )


FACTORIES = [
    ("CBD", "Carabao Distillery", "CBD"),
    ("APM", "Asia Pacific Manufacturing", "D365"),
    ("APG", "Asia Pacific Glass", "D365"),
    ("ACM", "Asia Can Manufacturing", "D365"),
]

# Central group standard (Carabao_Group_Item_Master, approved Aug 2026):
# one code for one item, whichever plant opens it.
#   [Item Group 3][Sub-Category 2][Item Type 2 = 00][Running 4]
# Sub-Category is always >= 01, so central codes can never collide with the
# 11,377 legacy ACM/APM/APG codes, which all carry 0000 in digits 4-7.
#
# Legacy systems stay in the table but inactive: scope today is non-stock +
# service only (stock 99xx/8xx belongs to the stock team). Re-activating one
# is a config change, not a code change, when stock joins this portal later.
SYSTEMS = [
    ("CENTRAL", "รหัสกลาง Carabao Group (Non-Stock + Service)", "{group}{sub}00{run:4}", True),
    ("CBD_STOCK", "CBD — Spare parts (Stock) [เลิกใช้]", "9905{cat}{sub}{run:4}", False),
    ("CBD_NONSTOCK", "CBD — Non-Spare parts [เลิกใช้]", "64{cat}{run:6}", False),
    ("D365_STOCK", "D365 — Stock [ทีม Stock ดูแล]", "{group}0000{run:4}", False),
    ("D365_NONSTOCK", "D365 — Non-Stock [เลิกใช้]", "{group}0000{run:4}", False),
    ("D365_SERVICE", "D365 — Service [เลิกใช้]", "{group}0000{run:4}", False),
]

# Every plant now requests against the one central system.
FACTORY_SYSTEMS = {
    "CBD": ["CENTRAL"],
    "APM": ["CENTRAL"],
    "APG": ["CENTRAL"],
    "ACM": ["CENTRAL"],
}

D365_STOCK_GROUPS = [
    ("800", "Spare part / Mechanic Part", "อะไหล่สำรองเครื่องจักร/อุปกรณ์"),
    ("801", "Oil", "น้ำมันหล่อลื่น เกียร์ ไฮดรอลิค น้ำยาเคลือบผิวขวด"),
    ("802", "Plate", "แม่พิมพ์เครื่องพิมพ์กราเวีย/เฟล็กโซ่"),
    ("803", "Chemical", "เคมีภัณฑ์โรงงาน/ทำความสะอาด แก๊ส"),
    ("804", "Tooling", "เครื่องมือและอุปกรณ์ช่าง"),
    ("805", "Consume", "วัสดุสิ้นเปลืองโรงงานและสำนักงาน"),
    ("806", "Mould", "Mould ขึ้นรูปขวด (APG) — โครงสร้างพิเศษ 806+type+run5"),
]

# Mould types under group 806 (from D365 stock rule sheet); code = digits 4-6.
MOULD_TYPES = [
    ("001", "AP-01 150 ml. CARABAO"),
    ("002", "AP-08 330 ml. Khao hom"),
    ("003", "AP-09 620 ml. LEO Beer"),
    ("004", "AP-22 GALAXY 350 ML."),
    ("005", "AP-12 WHISKEY 360 ML Tae yang"),
    ("006", "AP-18 WHISKEY 350 ML Tendo"),
    ("007", "AP-24 KACHA 375 ML"),
    ("008", "AP-17A 625 ml. Khao hom"),
    ("009", "AP-37 620 ml. TWD Beer"),
    ("010", "AP-10 140 ML. C+Lock"),
    ("011", "AP-16 WHISKEY 700 ML TENDO"),
    ("012", "AP-21 WHISKEY 700 ML Rattanakosin 158 Bottle"),
    ("013", "AP-01 CARABAO 150 ml.NNPB"),
    ("014", "AP-38 CARABAO BEER 320 ml."),
    ("015", "AP-39 CARABAO 150ml. NNPB 120 g."),
]

D365_NONSTOCK_GROUPS = [
    ("900", "Spare Parts & Mechanical Parts", "SPT"),
    ("901", "Electrical Parts", "SPT"),
    ("902", "Lab Instruments", "SPT"),
    ("903", "Chemicals (Oil & Gas)", "SPT"),
    ("904", "Construction Materials", "SPT"),
    ("905", "Factory Consume", "SPT"),
    ("906", "General Consume", "GN"),
    ("907", "IT Hardware & Accessories", "GN"),
    ("908", "Marketing", "GN"),
]

D365_SERVICE_GROUPS = [
    ("700", "Installation & Repair Machinery", "SPT"),
    ("701", "Construction & Civil & Utility", "SPT"),
    ("702", "Calibration & Certification Service", "SPT"),
    ("703", "Tools & Electrical Equip. Service", "SPT"),
    ("704", "Safety & Environmental Service", "SPT"),
    ("705", "Rental", "SPT"),
    ("706", "Marketing Service", "GN"),
    ("707", "IT Software & Service", "GN"),
    ("708", "Generals Service", "GN"),
    ("709", "Logistic & Transport", "SPT"),
    ("710", "Others Service", "SPT & GN"),
]

# CBD stock: category (digits 5-6) -> subcategories (digits 7-8)
CBD_STOCK_CATS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("01", "SM — Mechanical spare part", [
        ("01", "Bearing"), ("02", "O-ring, Seal & Gasket"), ("03", "Bolt & nut"),
        ("04", "Chain & Conveyor"), ("05", "Spring and bush"), ("06", "Miscellaneous"),
    ]),
    ("02", "SP — Pneumatic spare part", [
        ("01", "Cylinder"), ("02", "Actuator and valve"), ("03", "Tube and piping"),
        ("04", "Solenoid"), ("05", "Miscellaneous"),
    ]),
    ("03", "SE — Electrical spare part", [
        ("01", "Sensor"), ("02", "Breaker"), ("03", "Electrical module & board"),
        ("04", "Encoder"), ("05", "Inverter"), ("06", "Power supply"),
        ("07", "Cable & Connector"), ("08", "Others Electrical component"),
    ]),
    ("04", "SC — Consumable spare part", [
        ("01", "Filter"), ("02", "Lubricant"), ("03", "Miscellaneous"),
    ]),
    ("05", "ST — Tools", []),
    ("06", "SMO — Motor/Pump/Gear", [
        ("01", "Motor"), ("02", "Water pump"), ("03", "Gear"),
    ]),
    ("99", "อื่นๆ", []),
]

# CBD non-stock categories: from rule doc + categories found in real data (2026-07)
CBD_NONSTOCK_CATS = [
    ("SV", "งานบริการ, งานซ่อมสร้าง"),
    ("SVSP", "อะไหล่ที่ต้องเปลี่ยนระหว่างงานซ่อมสร้าง (run 4 หลัก)"),
    ("FQ", "อุปกรณ์โรงงานอื่นๆ"),
    ("MD", "สินค้า + งานบริการเกี่ยวกับการตลาด"),
    ("CS", "สินค้าสิ้นเปลืองอื่นๆ"),
    ("IT", "สินค้า + งานบริการเกี่ยวกับ IT"),
    ("OF", "ของใช้สำนักงาน"),
    ("SF", "อุปกรณ์ Safety"),
    ("BD", "เครื่องมือ ของใช้ในอาคาร"),
    ("WF", "สินค้าเพื่อสวัสดิการพนักงาน"),
    ("MC", "เครื่องจักร"),
    ("FL", "สินค้า + บริการเกี่ยวกับ Forklift"),
    ("LQ", "อุปกรณ์ Lab, อุปกรณ์วัดค่าต่างๆ"),
    ("CH", "เคมี Lab (พบในข้อมูลจริง)"),
    ("FU", "เชื้อเพลิง/แก๊ส (พบในข้อมูลจริง)"),
    ("MS", "Sticker/วัสดุอื่นๆ (พบในข้อมูลจริง)"),
    ("OT", "อื่นๆ (พบในข้อมูลจริง)"),
    ("SP", "อะไหล่ (พบในข้อมูลจริง)"),
    ("TR", "เดินทาง/ตั๋ว (พบในข้อมูลจริง)"),
    ("VE", "ยานพาหนะ (พบในข้อมูลจริง)"),
]


# UOM options seen in the temp import files; Peter completes the AX-valid list.
UOMS = [
    ("Pcs", "ชิ้น (Pcs)"),
    ("PC", "ชิ้น (PC)"),
    ("Set", "ชุด (Set)"),
    ("Job", "งาน (Job)"),
    ("JOB", "งาน (JOB)"),
]

# Group -> D365 export codes. Seeded from observed temp values where known;
# blanks are completed by Peter via admin (export still works, uses defaults).
GROUP_EXPORT_MAP = {
    # system_code, group_code : (item_group_id, model_group_id, group_type_code)
    ("D365_SERVICE", "707"): ("EN-FS", "EN", "SP"),
}


# Canonical search-name vocabulary, curated from the real CBD master (terms that
# actually cluster items). Multi-word terms first so specific beats generic.
SEARCH_TERMS = [
    "BALL BEARING", "PLAIN BEARING", "ROLLER BEARING", "DEEP GROOVE BEARING",
    "BEARING", "OIL SEAL", "SHAFT SEAL", "O-RING", "GASKET", "WEAR STRIP",
    "WEAR STRIP PROFILE", "CHAIN SPROCKET", "CHAIN WHEEL", "SPROCKET", "STARWHEEL",
    "TOOTHED BELT", "TIMING BELT", "V-BELT", "BELT", "ROLLER", "SHAFT",
    "ROTARY SHAFT", "PIN", "RETAINING RING", "RING", "GUIDE", "PRESSURE SPRING",
    "SPRING", "BUSH", "BUSHING", "COVER BUSH", "SLEEVE", "SPACER", "SHIM", "WASHER",
    "PLATE", "DEAD PLATE", "SUPPORT", "COVER", "BRACKET", "CYLINDER",
    "STANDARD CYLINDER", "FILTER", "SOLENOID VALVE", "BUTTERFLY VALVE",
    "CHECK VALVE", "BALL VALVE", "VALVE", "CIRCUIT BREAKER", "CONTACTOR",
    "FREQUENCY CONVERTER", "INVERTER", "SENSOR", "PROXIMITY SENSOR", "MOTOR",
    "GEAR MOTOR", "PUMP", "WATER PUMP", "GEAR", "COUPLING", "HEXAGON SCREW",
    "SCREW", "BOLT", "NUT", "SERVICE KIT", "SEAL KIT", "DIAPHRAGM", "NOZZLE",
    "HOSE", "FITTING", "CABLE", "CONNECTOR", "RELAY", "FUSE", "SWITCH",
    "SOFTWARE LICENSE", "STICKER", "BANNER", "LABEL",
    # Thai category words mined from the real CBD master (leading head words).
    # The master is bilingual; without these, Thai items get no category at all.
    # compound terms first — they are genuinely distinct categories in the
    # master, and the longest match wins (แหวนสปริง must not resolve to สปริง)
    "แหวนสปริง", "แหวนอีแปะ", "แหวนรอง", "หัวน็อต", "สกรูหัวจม", "สกรูหกเหลี่ยม",
    "ตะปูคอนกรีต", "ข้อต่อลม", "สายพานลำเลียง", "ลูกปืนตุ๊กตา",
    "ตะปู", "สกรู", "น็อต", "แหวน", "ลูกปืน", "ตลับลูกปืน", "สายพาน", "โซ่",
    "ข้องอ", "ข้อต่อ", "ข้อต่อตรง", "สามทาง", "ท่อ", "วาล์ว", "บอลวาล์ว",
    "สายไฟ", "สายลม", "สายยาง", "หลอดไฟ", "แบตเตอรี่", "เบรกเกอร์", "มอเตอร์",
    "ปั๊ม", "พัดลม", "เพลา", "เพลากลม", "ปะเก็น", "ซีล", "โอริง", "สปริง",
    "ดอกสว่าน", "ใบมีด", "เหล็กกล่อง", "สแตนเลสกล่อง", "แผ่นเหล็ก",
    "น้ำมัน", "จาระบี", "น้ำยา", "หัวเชื้อ", "น้ำหมึก", "หมึก", "ผ้าหมึก",
    "กระดาษ", "กระดาษกรอง", "สติ๊กเกอร์", "ใบปลิว", "ถุงพลาสติก", "กล่อง",
    "เสื้อ", "เสื้อโปโล", "กางเกง", "รองเท้า", "รองเท้ายาง", "ถุงมือ",
    "หน้ากาก", "แว่นตานิรภัย", "หมวกนิรภัย", "ชุดตรวจ", "ยา",
    # Service actions. Users type the verb without the 'งาน' prefix
    # ('ติดตั้งเครื่องแพ็คกล่อง'), so both forms must be in the vocabulary.
    "งานสอบเทียบ", "งานซ่อม", "งานติดตั้ง", "ค่าบริการ", "ค่าเช่า", "ค่าขนส่ง",
    "ติดตั้ง", "ซ่อม", "ซ่อมแซม", "สอบเทียบ", "ปรับปรุง", "บำรุงรักษา",
    "ตรวจสอบ", "ทำความสะอาด", "เช่า", "ขนส่ง", "ก่อสร้าง", "ต่อเติม",
    "รื้อถอน", "ออกแบบ", "ที่ปรึกษา", "ฝึกอบรม", "จ้างเหมา",
]


def load_thai_labels(
    raw: dict, taxonomy: list[dict],
) -> dict[str, tuple[str | None, str | None]]:
    """Check app/data/taxonomy_th.json against the taxonomy before any write.

    Every key must be a group ("900") or group-sub ("900-02") of the
    taxonomy; values are {"name_th": ..., "hint_th": ...}, both optional.
    """
    keys = {r["group"] for r in taxonomy} | {f"{r['group']}-{r['sub']}" for r in taxonomy}
    out: dict[str, tuple[str | None, str | None]] = {}
    for key, value in raw.items():
        if key not in keys:
            raise SeedError(f"app/data/taxonomy_th.json: ไม่มีหมวด '{key}' ใน taxonomy.json")
        if not isinstance(value, dict):
            raise SeedError(f"app/data/taxonomy_th.json: '{key}' ต้องเป็น {{\"name_th\": ..., \"hint_th\": ...}}")
        try:
            out[key] = (
                clean_label(value.get("name_th"), NAME_TH_MAX, f"ชื่อไทยของ {key} "),
                clean_label(value.get("hint_th"), HINT_TH_MAX, f"ตัวอย่างของ {key} "),
            )
        except LabelError as e:
            raise SeedError(f"app/data/taxonomy_th.json: {e}") from e
    return out


def seed(db: Session) -> None:
    taxonomy = _load_json("taxonomy.json")
    check_taxonomy(taxonomy)  # before the first write
    thai_labels = load_thai_labels(_load_json("taxonomy_th.json"), taxonomy)
    factories: dict[str, Factory] = {}
    for code, name, item_source in FACTORIES:
        f = db.scalar(select(Factory).where(Factory.code == code))
        if f is None:
            f = Factory(code=code, name=name, item_source=item_source)
            db.add(f)
            db.flush()
        elif f.item_source != item_source:
            f.item_source = item_source
        factories[code] = f

    systems: dict[str, CodeSystem] = {}
    for code, name_th, tpl, active in SYSTEMS:
        s = db.scalar(select(CodeSystem).where(CodeSystem.code == code))
        if s is None:
            s = CodeSystem(
                code=code, name_th=name_th, pattern_template=tpl, active=active
            )
            db.add(s)
            db.flush()
        else:
            s.name_th, s.pattern_template, s.active = name_th, tpl, active
        systems[code] = s

    for fcode, scodes in FACTORY_SYSTEMS.items():
        for scode in scodes:
            exists = db.scalar(
                select(FactoryCodeSystem).where(
                    FactoryCodeSystem.factory_id == factories[fcode].id,
                    FactoryCodeSystem.code_system_id == systems[scode].id,
                )
            )
            if exists is None:
                db.add(
                    FactoryCodeSystem(
                        factory_id=factories[fcode].id,
                        code_system_id=systems[scode].id,
                    )
                )

    def ensure_group(
        system: CodeSystem, code: str, name: str,
        scope: str | None = None, parent: CodeGroup | None = None,
        pattern_override: str | None = None,
        name_prefix: str | None = None, product_type: str | None = None,
    ) -> CodeGroup:
        g = db.scalar(
            select(CodeGroup).where(
                CodeGroup.code_system_id == system.id,
                CodeGroup.code == code,
                CodeGroup.parent_id == (parent.id if parent else None),
            )
        )
        if g is None:
            g = CodeGroup(
                code_system_id=system.id, code=code, name=name,
                scope_note=scope, parent_id=parent.id if parent else None,
                pattern_override=pattern_override,
                name_prefix=name_prefix, product_type=product_type,
            )
            db.add(g)
            db.flush()
        elif pattern_override and g.pattern_override != pattern_override:
            g.pattern_override = pattern_override
        return g

    # --- Central taxonomy: 20 Item Groups / 130 Sub-Categories -------------
    # Source of truth is app/data/taxonomy.json, extracted from the approved
    # 'Taxonomy' sheet of Carabao_Group_Item_Master_Central.
    central = systems["CENTRAL"]
    central_by_key: dict[str, CodeGroup] = {}
    for row in taxonomy:
        grp = ensure_group(central, row["group"], row["group_name"])
        sub = ensure_group(
            central, row["sub"], row["sub_name"], parent=grp,
            name_prefix=row["prefix"], product_type=row["product_type"],
        )
        sub.name_prefix = row["prefix"]
        sub.product_type = row["product_type"]
        central_by_key[row["group"]] = grp
        central_by_key[f"{row['group']}-{row['sub']}"] = sub

    # Thai names and hints (STORY-019). A row an Administrator saved on the
    # reference data page (th_edited, even to clear it) is never touched;
    # every other row follows app/data/taxonomy_th.json, so a corrected
    # wording reaches it and a key removed from the file clears it.
    for key, g in central_by_key.items():
        if not g.th_edited:
            g.name_th, g.hint_th = thai_labels.get(key, (None, None))

    # --- Central running register ------------------------------------------
    # Seeded with the last number already issued per Category+Sub so the portal
    # continues the group's series instead of restarting it.
    for row in _load_json("running_register.json"):
        reg = db.scalar(
            select(RunningRegister).where(
                RunningRegister.group_code == row["group"],
                RunningRegister.sub_code == row["sub"],
            )
        )
        if reg is None:
            db.add(RunningRegister(
                group_code=row["group"], sub_code=row["sub"],
                last_running=int(row["last"]),
            ))
        elif reg.last_running < int(row["last"]):
            # never move a counter backwards
            reg.last_running = int(row["last"])

    for code, name in UOMS:
        if db.scalar(select(Uom).where(Uom.code == code)) is None:
            db.add(Uom(code=code, name=name))

    for term in SEARCH_TERMS:
        if db.scalar(select(SearchTerm).where(SearchTerm.term == term)) is None:
            db.add(SearchTerm(term=term))

    # Procurement categories observed in the temp files; Peter completes the list.
    for source, label in [
        ("D365", "54050102 Computer expenses (54050102 Computer expenses)"),
        ("D365", "54080401 MA - Outsource Maintenance (54080401 MA - Outsource Maintenance)"),
        ("D365", "54080601 MA-Overhaul"),
    ]:
        if db.scalar(
            select(ProcurementCategory).where(
                ProcurementCategory.source == source, ProcurementCategory.label == label
            )
        ) is None:
            db.add(ProcurementCategory(source=source, label=label))

    for (sys_code, grp_code), (igid, mgid, gtc) in GROUP_EXPORT_MAP.items():
        grp = db.scalar(
            select(CodeGroup).where(
                CodeGroup.code_system_id == systems[sys_code].id,
                CodeGroup.code == grp_code,
                CodeGroup.parent_id.is_(None),
            )
        )
        if grp and db.scalar(
            select(GroupExportMap).where(GroupExportMap.code_group_id == grp.id)
        ) is None:
            db.add(GroupExportMap(
                code_group_id=grp.id, item_group_id=igid,
                model_group_id=mgid, group_type_code=gtc,
            ))

    # Email domains for originator emails (STORY-002). Insert-only: a domain an
    # Administrator switched off stays off when seed runs again.
    for domain in _load_json("mail_domains.json"):
        domain = domain.strip().lower()
        if db.scalar(select(MailDomain).where(MailDomain.domain == domain)) is None:
            db.add(MailDomain(domain=domain))

    db.commit()


def main() -> int:
    try:
        with SessionLocal() as session:
            seed(session)
    except SeedError as e:
        print(e, file=sys.stderr)
        return 1
    print("Seed complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
