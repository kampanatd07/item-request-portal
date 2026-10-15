"""STORY-002 ticket 05: the originator's email, and who gets the emails."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text

from app.config import settings
from app.models import ItemRequest, RequestEvent
from app.services.exporter import export_pending
from app.services.notify import build_created_email, recipients
from app.services.requests import RequestError, change_status, originator_of, submit_request
from tests.conftest import account_for, central_ids

def _submit(db, account=None, **kw):
    factory, system, group, sub = central_ids(db)
    return submit_request(db, account or account_for(db), factory_id=factory.id,
                          code_system_id=system.id, group_id=group.id, subgroup_id=sub.id,
                          item_name="Ball Bearing", **kw)


# --- Migration backfill (HANDOFF §6: no \b next to Thai, NFC + SARA AM) -------------------------

def test_migration_backfills_names_from_on_behalf_lines(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    url = f"sqlite:///{(tmp_path / 'origin.db').as_posix()}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    command.upgrade(cfg, "16ec6f1afac9")  # before the originator columns
    engine = create_engine(url)
    details = {
        "composed": "ขอแทน: คำรณ ใจดี",                               # SARA AM, one code point
        "decomposed": "ขอแทน: คํารณ   ทองดี",                # NIKHAHIT + SARA AA, extra spaces
        "angle_brackets": "ขอแทน: สมชาย <ฝ่ายซ่อมบำรุง>",               # typed as is, kept whole
        "bare_lt": "ขอแทน: A < B",
        "crlf": "duplicate candidates: x\r\nขอแทน: วิชัย ทองคำ\r\nmore",
        "new_format": "ขอแทน: คำรณ ใจดี <kamron@carabao.co.th>",      # after downgrade+upgrade
        "multi_line": "duplicate candidates: 90001000001 X (90%)\nขอแทน: นำชัย  ศรีสุข\n",
        "not_a_line": "หมายเหตุ ไม่ขอแทน: ใคร",                         # not at line start
        "none": "duplicate candidates: 90001000002 Y (80%)",
        "fullwidth": "ขอแทน: คำรณ ＡＢＣ",                              # NFKC would turn this into ABC
    }
    ids = {}
    try:
        with engine.begin() as c:
            for key, detail in details.items():
                c.execute(text(
                    "INSERT INTO item_requests (requester_name, requester_email, factory_id, "
                    "code_system_id, group_id, item_name, status) "
                    "VALUES ('P', 'p@test.local', 1, 1, 1, 'x', 'submitted')"))
                ids[key] = c.execute(text("SELECT max(id) FROM item_requests")).scalar()
                c.execute(text(
                    "INSERT INTO request_events (request_id, actor, action, detail, at) "
                    "VALUES (:r, 'p@test.local', 'submitted', :d, '2026-09-30 10:00:00')"),
                    {"r": ids[key], "d": detail})
        command.upgrade(cfg, "head")
        with engine.connect() as c:
            got = dict(c.execute(text("SELECT id, originator_name FROM item_requests")).all())
    finally:
        engine.dispose()

    assert got[ids["composed"]] == "คำรณ ใจดี"
    assert got[ids["decomposed"]] == "คำรณ ทองดี"          # recomposed to SARA AM, spaces collapsed
    assert got[ids["decomposed"]] == got[ids["composed"]].replace("ใจดี", "ทองดี")
    assert got[ids["angle_brackets"]] == "สมชาย <ฝ่ายซ่อมบำรุง>"
    assert got[ids["bare_lt"]] == "A < B"
    assert got[ids["crlf"]] == "วิชัย ทองคำ"
    assert got[ids["new_format"]] == "คำรณ ใจดี"             # the appended email is not the name
    assert got[ids["multi_line"]] == "นำชัย ศรีสุข"
    assert got[ids["not_a_line"]] is None
    assert got[ids["none"]] is None
    assert got[ids["fullwidth"]] == "คำรณ ＡＢＣ"           # NFC keeps what was typed (HANDOFF §6.2)


# --- The originator email rules (AC7) -----------------------------------------------------------

def test_originator_email_is_stored_lowercase_with_the_name(db_session):
    req = _submit(db_session, on_behalf_of="  คำรณ  ใจดี ", originator_email=" Kamron@Carabao.co.th ")
    assert (req.originator_name, req.originator_email) == ("คำรณ ใจดี", "kamron@carabao.co.th")
    assert originator_of(req) == "คำรณ ใจดี"
    detail = db_session.scalar(select(RequestEvent.detail).where(
        RequestEvent.request_id == req.id, RequestEvent.action == "submitted"))
    assert "ขอแทน: คำรณ ใจดี <kamron@carabao.co.th>" in detail


@pytest.mark.parametrize("name,email,message", [
    ("", "a@carabao.co.th", "ต้องใส่ชื่อ"),
    ("คำรณ", "not-an-email", "รูปแบบ"),
    ("คำรณ", "a b@carabao.co.th", "รูปแบบ"),
    ("คำรณ", "a@gmail.com", "โดเมนของบริษัท"),
    ("คำรณ", "a@x.carabao.co.th", "โดเมนของบริษัท"),       # exact match only
    ("คำรณ", "a@carabao.co.th.evil.com", "โดเมนของบริษัท"),
])
def test_bad_originator_email_is_refused(db_session, name, email, message):
    with pytest.raises(RequestError, match=message):
        _submit(db_session, on_behalf_of=name, originator_email=email)
    assert db_session.scalar(select(ItemRequest)) is None


def test_no_active_domain_refuses_originator_emails(db_session):
    from app.models import MailDomain

    for d in db_session.scalars(select(MailDomain)):
        d.active = False
    db_session.commit()
    with pytest.raises(RequestError, match="ยังไม่มีโดเมนอีเมลที่อนุญาต"):
        _submit(db_session, on_behalf_of="คำรณ", originator_email="a@carabao.co.th")


def test_name_without_email_is_still_fine(db_session):
    req = _submit(db_session, on_behalf_of="คำรณ ใจดี")
    assert (req.originator_name, req.originator_email) == ("คำรณ ใจดี", None)


def test_every_seeded_plant_domain_is_accepted(db_session):
    for domain in ("apm.co.th", "acmf.co.th", "apg.co.th", "carabao.co.th"):
        req = _submit(db_session, on_behalf_of="A", originator_email=f"A@{domain.upper()}")
        assert req.originator_email == f"a@{domain}"


def test_a_switched_off_domain_is_refused(db_session):
    from app.models import MailDomain

    d = db_session.scalar(select(MailDomain).where(MailDomain.domain == "apg.co.th"))
    d.active = False
    db_session.commit()
    with pytest.raises(RequestError, match="โดเมนของบริษัท"):
        _submit(db_session, on_behalf_of="A", originator_email="a@apg.co.th")


def test_requester_cannot_set_originator_fields(db_session):
    requester = account_for(db_session, "requester", plant="APM")
    req = _submit(db_session, requester, on_behalf_of="คนอื่น", originator_email="x@carabao.co.th")
    assert (req.originator_name, req.originator_email) == (None, None)


# --- Recipient rule -------------------------------------------------------------------------------

def test_originator_gets_the_email_and_the_submitter_a_copy(db_session):
    req = _submit(db_session, on_behalf_of="คำรณ ใจดี", originator_email="kamron@carabao.co.th")
    assert recipients(req) == (["kamron@carabao.co.th"], ["procurement-any@test.local"])


def test_without_originator_email_the_submitter_gets_it(db_session):
    assert recipients(_submit(db_session, on_behalf_of="คำรณ")) == (
        ["procurement-any@test.local"], [])
    assert recipients(_submit(db_session)) == (["procurement-any@test.local"], [])


def test_created_email_greets_and_reaches_the_originator(client, app_db, mail_outbox):
    req = _submit(app_db, on_behalf_of="คำรณ ใจดี", originator_email="kamron@carabao.co.th")
    change_status(app_db, req.id, new_status="approved", account=account_for(app_db, "administrator"))
    batch = export_pending(app_db, req.factory_id, account=account_for(app_db))
    client.post(f"/exports/{batch.id}/mark-created")
    [mail] = mail_outbox.sent
    assert mail.to == ["kamron@carabao.co.th"] and mail.cc == ["procurement-any@test.local"]
    assert "เรียน คำรณ ใจดี" in mail.html and "เรียน คำรณ ใจดี" in mail.text


def test_build_created_email_uses_the_rule(db_session):
    req = _submit(db_session, on_behalf_of="คำรณ", originator_email="kamron@carabao.co.th")
    req.generated_code = "90001000999"
    mail = build_created_email(req)
    assert (mail.to, mail.cc) == (["kamron@carabao.co.th"], ["procurement-any@test.local"])


# --- Screens --------------------------------------------------------------------------------------

def test_form_offers_the_originator_email_to_procurement_only(client_as):
    assert 'name="originator_email"' in client_as("procurement").get("/").text
    assert 'name="originator_email"' not in client_as("requester", plant="APM").get("/").text


def test_form_post_saves_and_detail_page_shows_it(client, app_db):
    factory, system, group, sub = central_ids(app_db)
    r = client.post("/requests", data={
        "factory_id": factory.id, "code_system_id": system.id, "group_id": group.id,
        "subgroup_id": sub.id, "item_name": "Ball Bearing",
        "on_behalf_of": "คำรณ ใจดี", "originator_email": "kamron@carabao.co.th"})
    assert r.status_code == 200
    req = app_db.scalar(select(ItemRequest))
    page = client.get(f"/queue/{req.id}").text
    assert "คำรณ ใจดี" in page and "kamron@carabao.co.th" in page


def test_form_post_with_a_bad_domain_is_a_thai_422(client, app_db):
    factory, system, group, sub = central_ids(app_db)
    r = client.post("/requests", data={
        "factory_id": factory.id, "code_system_id": system.id, "group_id": group.id,
        "subgroup_id": sub.id, "item_name": "Ball Bearing",
        "on_behalf_of": "คำรณ", "originator_email": "kamron@gmail.com"})
    assert r.status_code == 422 and "โดเมนของบริษัท" in r.text


def test_form_post_with_an_email_but_no_name_is_a_thai_422(client, app_db):
    factory, system, group, sub = central_ids(app_db)
    before = app_db.scalar(select(func.count()).select_from(ItemRequest))
    r = client.post("/requests", data={
        "factory_id": factory.id, "code_system_id": system.id, "group_id": group.id,
        "subgroup_id": sub.id, "item_name": "Ball Bearing",
        "on_behalf_of": "  ", "originator_email": "kamron@carabao.co.th"})
    assert r.status_code == 422 and "ต้องใส่ชื่อ" in r.text
    assert app_db.scalar(select(func.count()).select_from(ItemRequest)) == before



def test_originator_name_is_nfc_with_sara_am_recomposed(db_session):
    req = _submit(db_session, on_behalf_of="ค\u0e4d\u0e32รณ ใจดี")  # NIKHAHIT + SARA AA
    assert req.originator_name == "คำรณ ใจดี"


@pytest.mark.parametrize("name,email,message", [
    ("ก" * 101, None, "ชื่อผู้ขอจริงยาวเกิน 100"),
    ("คำรณ", "a" * 241 + "@carabao.co.th", "อีเมลผู้ขอจริงยาวเกิน 254"),   # 255 chars
])
def test_lengths_over_the_columns_are_a_thai_error(db_session, name, email, message):
    with pytest.raises(RequestError, match=message):
        _submit(db_session, on_behalf_of=name, originator_email=email)


def test_names_and_emails_at_the_limit_are_fine(db_session):
    email = "a" * 240 + "@carabao.co.th"  # 254 chars
    req = _submit(db_session, on_behalf_of="ก" * 100, originator_email=email)
    assert len(req.originator_name) == 100 and req.originator_email == email



# --- Allowed domains are data (Settings page) ---------------------------------------------------

def test_seed_puts_the_four_domains_once_and_keeps_switched_off_ones_off(db_session):
    from app.models import MailDomain
    from app.seed import seed

    d = db_session.scalar(select(MailDomain).where(MailDomain.domain == "apm.co.th"))
    d.active = False
    db_session.commit()
    seed(db_session)
    seed(db_session)
    rows = {m.domain: m.active for m in db_session.scalars(select(MailDomain))}
    assert rows == {"apm.co.th": False, "acmf.co.th": True, "apg.co.th": True,
                    "carabao.co.th": True}


def test_administrator_adds_a_domain_on_the_settings_page_and_it_works(client, app_db):
    r = client.post("/admin/config/mail-domain", data={"domain": "  @Carabao-Group.CO.TH "})
    assert r.status_code == 200 and "carabao-group.co.th" in r.text
    req = _submit(app_db, on_behalf_of="A", originator_email="a@carabao-group.co.th")
    assert req.originator_email == "a@carabao-group.co.th"


@pytest.mark.parametrize("bad", ["", "carabao", "carabao.co.th/x", "a b.co.th", "-x.co.th",
                                 "x..co.th", "คาราบาว.co.th", "carabao.co.t"])
def test_bad_domain_format_is_refused_in_thai(client, app_db, bad):
    r = client.post("/admin/config/mail-domain", data={"domain": bad})
    assert r.status_code == 422 and "รูปแบบโดเมนไม่ถูกต้อง" in r.text


def test_duplicate_domain_is_refused(client):
    r = client.post("/admin/config/mail-domain", data={"domain": "CARABAO.co.th"})
    assert r.status_code == 422 and "มีอยู่แล้ว" in r.text


def test_switching_a_domain_off_and_on_on_the_settings_page(client, app_db):
    from app.models import MailDomain

    d = app_db.scalar(select(MailDomain).where(MailDomain.domain == "acmf.co.th"))
    client.post(f"/admin/config/mail-domain/{d.id}/toggle")
    app_db.refresh(d)
    assert d.active is False
    with pytest.raises(RequestError):
        _submit(app_db, on_behalf_of="A", originator_email="a@acmf.co.th")
    client.post(f"/admin/config/mail-domain/{d.id}/toggle")
    app_db.refresh(d)
    assert d.active is True


@pytest.mark.parametrize("role,plant", [("procurement", None), ("requester", "APM")])
def test_only_administrators_edit_domains(client_as, role, plant):
    c = client_as(role, plant=plant)
    assert c.post("/admin/config/mail-domain", data={"domain": "x.co.th"}).status_code == 403
    assert c.post("/admin/config/mail-domain/1/toggle").status_code == 403


def test_settings_page_lists_the_domains(client):
    page = client.get("/admin/config").text
    assert "โดเมนอีเมลที่อนุญาต" in page
    for domain in ("apm.co.th", "acmf.co.th", "apg.co.th", "carabao.co.th"):
        assert domain in page



def test_a_domain_switched_off_after_submission_is_not_emailed(db_session):
    from app.models import MailDomain

    req = _submit(db_session, on_behalf_of="คำรณ", originator_email="kamron@apg.co.th")
    d = db_session.scalar(select(MailDomain).where(MailDomain.domain == "apg.co.th"))
    d.active = False
    db_session.commit()
    assert recipients(req) == (["procurement-any@test.local"], [])
    req.generated_code = "90001000999"
    mail = build_created_email(req)
    assert "kamron@apg.co.th" not in mail.to + mail.cc
    assert "เรียน Test procurement" in mail.text  # greets the submitter it goes to


def test_same_address_is_not_repeated_in_cc(db_session):
    from app.services.auth import create_account

    me = create_account(db_session, "me@carabao.co.th", "Me", "procurement", "a-long-password-1",
                        must_change_password=False)
    req = _submit(db_session, me, on_behalf_of="Me", originator_email="ME@carabao.co.th")
    assert recipients(req) == (["me@carabao.co.th"], [])



def test_notified_event_says_the_domain_was_switched_off(client, app_db, mail_outbox):
    from app.models import MailDomain

    req = _submit(app_db, on_behalf_of="คำรณ", originator_email="kamron@apg.co.th")
    change_status(app_db, req.id, new_status="approved", account=account_for(app_db, "administrator"))
    batch = export_pending(app_db, req.factory_id, account=account_for(app_db))
    d = app_db.scalar(select(MailDomain).where(MailDomain.domain == "apg.co.th"))
    d.active = False
    app_db.commit()

    client.post(f"/exports/{batch.id}/mark-created")
    [mail] = mail_outbox.sent
    assert mail.to == ["procurement-any@test.local"] and mail.cc == []
    detail = app_db.scalar(select(RequestEvent.detail).where(
        RequestEvent.request_id == req.id, RequestEvent.action == "notified"))
    assert "โดเมน apg.co.th ถูกปิด — ส่งให้ผู้ส่งคำขอแทน" in detail


def test_notified_event_has_no_note_when_the_domain_is_active(client, app_db, mail_outbox):
    req = _submit(app_db, on_behalf_of="คำรณ", originator_email="kamron@apg.co.th")
    change_status(app_db, req.id, new_status="approved", account=account_for(app_db, "administrator"))
    batch = export_pending(app_db, req.factory_id, account=account_for(app_db))
    client.post(f"/exports/{batch.id}/mark-created")
    detail = app_db.scalar(select(RequestEvent.detail).where(
        RequestEvent.request_id == req.id, RequestEvent.action == "notified"))
    assert "kamron@apg.co.th" in detail and "ถูกปิด" not in detail
