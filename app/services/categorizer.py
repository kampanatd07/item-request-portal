"""Suggest the central category (Group + Sub-Category) for a typed item name.

Picking from 20 groups x 130 sub-categories is too much to ask of a factory
user, so the system proposes and the user confirms.

Three sources, in order of trustworthiness:

1. **Neighbours in the classified master** — 13k items already carry central
   labels. Similar names vote, weighted by similarity. Measured on a 300-item
   holdout: 59% correct at rank 1, 71% within the top 3. That gap is why the
   UI offers three chips instead of silently choosing.
2. **Keyword rules** — a small, explicit map for things with no neighbours yet.
3. **LLM** — optional last resort; absent an API key the first two still work.

Every suggestion carries its evidence (which items voted for it) so the user
can judge it and procurement can audit it.
"""

from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import CodeGroup, CodeSystem, ItemSnapshot
from app.services.snapshots import normalize, similarity

# Confidence at or above which the UI pre-selects the category for the user.
AUTO_SELECT_CONFIDENCE = 0.80

# Similarity at which a neighbour is treated as a genuine match. Below this the
# confidence is scaled down: unanimous agreement among distant neighbours is not
# the same as an exact match, and only the latter may auto-select.
STRONG_MATCH = 0.6

# Words that make an item a service regardless of what it acts upon. Without
# this, 'งานซ่อมปั๊มน้ำ' matches the many pump PARTS in the master and lands in
# 900-06 with full confidence — a confident wrong answer, the worst kind.
SERVICE_MARKERS = (
    "งานซ่อม", "งานติดตั้ง", "งานสร้าง", "งานปรับปรุง", "สอบเทียบ", "ค่าบริการ",
    "ค่าเช่า", "ค่าจ้าง", "ค่าขนส่ง", "บริการ", "repair", "service", "install",
    "calibration", "maintenance", "rental", "overhaul",
)

# Keyword -> (group, sub). Deliberately short: neighbours cover the long tail,
# these exist for terms that are unambiguous but may have no example yet.
KEYWORD_RULES: list[tuple[tuple[str, ...], tuple[str, str]]] = [
    (("bearing", "ลูกปืน", "ตลับลูกปืน"), ("900", "01")),
    (("o-ring", "oring", "โอริง", "ปะเก็น", "gasket", "seal", "ซีล"), ("900", "02")),
    (("bolt", "screw", "nut", "washer", "สกรู", "น็อต", "แหวน", "ตะปู"), ("900", "03")),
    (("valve", "วาล์ว", "fitting", "ข้องอ", "ข้อต่อ", "ท่อ", "pipe"), ("900", "04")),
    (("filter", "strainer", "กรอง"), ("900", "10")),
    (("motor", "มอเตอร์", "pump", "ปั๊ม", "gearbox"), ("900", "06")),
    (("breaker", "เบรกเกอร์", "contactor", "relay", "รีเลย์"), ("901", "01")),
    (("cable", "สายไฟ", "connector"), ("901", "03")),
    (("สอบเทียบ", "calibration", "calibrate"), ("702", "01")),
    (("งานซ่อม", "repair", "ซ่อมแซม"), ("700", "02")),
    (("pm ", "preventive", "บำรุงรักษา"), ("700", "03")),
    (("ถุงมือ", "glove", "หมวกนิรภัย", "safety", "ppe", "รองเท้าเซฟตี้"), ("905", "02")),
    (("กระดาษ", "paper", "ปากกา", "pen", "แฟ้ม"), ("906", "01")),
    (("notebook", "computer", "คอมพิวเตอร์", "printer", "เครื่องพิมพ์"), ("907", "01")),
]


class Suggestion:
    """One proposed category with the evidence behind it."""

    def __init__(self, group: CodeGroup, sub: CodeGroup, confidence: float,
                 source: str, examples: list[str] | None = None):
        self.group = group
        self.sub = sub
        self.confidence = confidence
        self.source = source
        self.examples = examples or []

    @property
    def label(self) -> str:
        return f"{self.group.code}-{self.sub.code} {self.sub.name}"


def _looks_like_service(name: str) -> bool:
    q = normalize(name)
    return any(normalize(m) in q for m in SERVICE_MARKERS)


def _central_groups(db: Session) -> dict[tuple[str, str], tuple[CodeGroup, CodeGroup]]:
    """(group_code, sub_code) -> (group, sub) for the active central taxonomy."""
    system = db.scalar(select(CodeSystem).where(CodeSystem.code == "CENTRAL"))
    if system is None:
        return {}
    groups = {
        g.id: g
        for g in db.scalars(
            select(CodeGroup).where(
                CodeGroup.code_system_id == system.id, CodeGroup.parent_id.is_(None)
            )
        )
    }
    out: dict[tuple[str, str], tuple[CodeGroup, CodeGroup]] = {}
    for sub in db.scalars(
        select(CodeGroup).where(
            CodeGroup.code_system_id == system.id, CodeGroup.parent_id.is_not(None)
        )
    ):
        parent = groups.get(sub.parent_id)
        if parent is not None:
            out[(parent.code, sub.code)] = (parent, sub)
    return out


def _neighbour_votes(
    db: Session, query: str, limit: int = 400
) -> list[tuple[tuple[str, str], float, str]]:
    """Return (label_key, weight, example_name) for labelled look-alikes."""
    q = normalize(query)
    tokens = [t for t in q.split() if len(t) >= 2][:6]
    if not tokens:
        return []
    stmt = (
        select(ItemSnapshot)
        .where(
            ItemSnapshot.group_code.is_not(None),
            or_(*[ItemSnapshot.normalized_name.like(f"%{t}%") for t in tokens]),
        )
        .limit(limit * 6)
    )
    scored = []
    for item in db.scalars(stmt):
        s = similarity(q, item.normalized_name)
        if s >= 0.2:
            scored.append((s, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        ((it.group_code, it.sub_code), s, it.name) for s, it in scored[:8]
    ]


def suggest_category(db: Session, name: str, *, llm=None) -> list[Suggestion]:
    """Up to three ranked suggestions. Empty list when nothing is confident."""
    catalog = _central_groups(db)
    if not catalog or not (name or "").strip():
        return []

    wants_service = _looks_like_service(name)
    votes: dict[tuple[str, str], float] = defaultdict(float)
    evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
    best_similarity = 0.0
    for key, weight, example in _neighbour_votes(db, name):
        if key not in catalog:
            continue
        # A service request must not be answered with a parts category just
        # because it names the machine the work is done on.
        sub = catalog[key][1]
        if wants_service and (sub.product_type or "").lower() == "item":
            continue  # a repair job is never a spare-part category
        votes[key] += weight
        best_similarity = max(best_similarity, weight)
        if len(evidence[key]) < 3:
            evidence[key].append(example)

    source = "neighbours"
    if not votes:
        q = normalize(name)
        for keywords, key in KEYWORD_RULES:
            if key not in catalog:
                continue
            if wants_service and (catalog[key][1].product_type or "").lower() == "item":
                continue
            if any(normalize(k) in q for k in keywords):
                votes[key] += 1.0
                source = "keyword"
                break

    if not votes and llm is not None:
        options = [f"{g}-{s}" for (g, s) in catalog]
        try:
            picked = llm(name, options)
        except Exception:
            picked = None
        if picked:
            parts = str(picked).strip().split("-")
            if len(parts) == 2 and (parts[0], parts[1]) in catalog:
                votes[(parts[0], parts[1])] = 1.0
                source = "llm"

    if not votes:
        return []

    # Confidence = how much the neighbours agree, tempered by how close the
    # closest one actually is. Keyword/LLM answers get a fixed moderate score:
    # they are useful hints but were never seen in real data.
    total = sum(votes.values())
    closeness = 1.0 if source != "neighbours" else min(1.0, best_similarity / STRONG_MATCH)
    ranked = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return [
        Suggestion(
            catalog[key][0], catalog[key][1],
            (weight / total) * (closeness if source == "neighbours" else 0.6),
            source, evidence.get(key),
        )
        for key, weight in ranked
    ]


def learn_from_correction(
    db: Session, *, name: str, group_code: str, sub_code: str, actor: str = "procurement"
) -> None:
    """Remember a human decision so similar future requests start out right.

    Stored as a labelled snapshot row, which is the same shape the suggester
    already reads — no separate model, no retraining step.
    """
    from app.models import SnapshotImport

    name = (name or "").strip()
    if not name:
        return
    normalized = normalize(name)
    existing = db.scalar(
        select(ItemSnapshot).where(
            ItemSnapshot.source == "LEARNED",
            ItemSnapshot.normalized_name == normalized,
        )
    )
    if existing is not None:
        existing.group_code, existing.sub_code = group_code, sub_code
        db.commit()
        return

    imp = db.scalar(
        select(SnapshotImport)
        .where(SnapshotImport.source == "LEARNED")
        .order_by(SnapshotImport.at.desc())
        .limit(1)
    )
    if imp is None:
        imp = SnapshotImport(
            source="LEARNED", filename="procurement corrections",
            row_count=0, uploaded_by=actor,
        )
        db.add(imp)
        db.flush()
    imp.row_count += 1
    db.add(
        ItemSnapshot(
            source="LEARNED", item_number=f"LEARN-{normalized[:20]}", name=name,
            normalized_name=normalized, group_code=group_code, sub_code=sub_code,
            import_id=imp.id,
        )
    )
    db.commit()
