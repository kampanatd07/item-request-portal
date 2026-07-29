"""Seed reference data: factories, code systems, and rule config.

Extracted from the verified rule documents (docs/rules/*.md). Idempotent:
safe to run repeatedly — inserts only what is missing, never deletes.
Run: python -m app.seed
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import CodeGroup, CodeSystem, Factory, FactoryCodeSystem

FACTORIES = [
    ("CBD", "Carabao Distillery", "CBD"),
    ("APM", "Asia Pacific Manufacturing", "D365"),
    ("APG", "Asia Pacific Glass", "D365"),
    ("ACM", "Asia Can Manufacturing", "D365"),
]

SYSTEMS = [
    ("CBD_STOCK", "CBD — Spare parts (Stock)", "9905{cat}{sub}{run:4}"),
    ("CBD_NONSTOCK", "CBD — Non-Spare parts", "64{cat}{run:6}"),
    ("D365_STOCK", "D365 — Stock", "{group}0000{run:4}"),
    ("D365_NONSTOCK", "D365 — Non-Stock", "{group}0000{run:4}"),
    ("D365_SERVICE", "D365 — Service", "{group}0000{run:4}"),
]

FACTORY_SYSTEMS = {
    "CBD": ["CBD_STOCK", "CBD_NONSTOCK"],
    "APM": ["D365_STOCK", "D365_NONSTOCK", "D365_SERVICE"],
    "APG": ["D365_STOCK", "D365_NONSTOCK", "D365_SERVICE"],
    "ACM": ["D365_STOCK", "D365_NONSTOCK", "D365_SERVICE"],
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


def seed(db: Session) -> None:
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
    for code, name_th, tpl in SYSTEMS:
        s = db.scalar(select(CodeSystem).where(CodeSystem.code == code))
        if s is None:
            s = CodeSystem(code=code, name_th=name_th, pattern_template=tpl)
            db.add(s)
            db.flush()
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
            )
            db.add(g)
            db.flush()
        elif pattern_override and g.pattern_override != pattern_override:
            g.pattern_override = pattern_override
        return g

    for code, name, scope in D365_STOCK_GROUPS:
        override = "{group}{sub}{run:5}" if code == "806" else None
        group = ensure_group(
            systems["D365_STOCK"], code, name, scope, pattern_override=override
        )
        if code == "806":
            for type_code, type_name in MOULD_TYPES:
                ensure_group(
                    systems["D365_STOCK"], type_code, type_name, parent=group
                )
    for code, name, scope in D365_NONSTOCK_GROUPS:
        ensure_group(systems["D365_NONSTOCK"], code, name, scope)
    for code, name, scope in D365_SERVICE_GROUPS:
        ensure_group(systems["D365_SERVICE"], code, name, scope)

    for cat_code, cat_name, subs in CBD_STOCK_CATS:
        cat = ensure_group(systems["CBD_STOCK"], cat_code, cat_name)
        for sub_code, sub_name in subs:
            ensure_group(systems["CBD_STOCK"], sub_code, sub_name, parent=cat)
        # Every category has a '99' catch-all subcategory in the real master
        # (e.g. 99050599, 99059999) — seeded so codegen never dead-ends.
        ensure_group(systems["CBD_STOCK"], "99", "อื่นๆ", parent=cat)

    for code, name in CBD_NONSTOCK_CATS:
        override = "64{cat}{run:4}" if code == "SVSP" else None
        ensure_group(systems["CBD_NONSTOCK"], code, name, pattern_override=override)

    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        seed(session)
    print("Seed complete.")
