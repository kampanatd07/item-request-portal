"""STORY-009 ticket 03: Procurement's "รับเข้าคิวใหม่" uses the resubmit claim."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ItemRequest, RequestEvent
from app.services import requests as svc
from app.services.requests import (
    RequestConflict,
    RequestError,
    change_status,
    requeue_request,
    resubmit_request,
    submit_request,
)
from tests.conftest import account_for, central_ids

NOTE = "ผู้ขอโทรมาแจ้งขนาดแล้ว"


def _needs_info_request(db: Session) -> ItemRequest:
    me = account_for(db, "requester", plant="APM")
    factory, system, group, sub = central_ids(db)
    req = submit_request(db, me, factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing",
                         brand="SKF")
    change_status(db, req.id, new_status="needs_info", note="ขอขนาด",
                  account=account_for(db, "procurement"))
    return req


def _events(db: Session, req: ItemRequest) -> list[RequestEvent]:
    db.expire_all()
    return list(db.scalars(select(RequestEvent).where(RequestEvent.request_id == req.id)
                           .order_by(RequestEvent.id)))


# --- 1/2. The note is required, in the service -----------------------------------------------------

@pytest.mark.parametrize("note", ["", "   ", None])
def test_requeue_without_a_note_is_refused_and_changes_nothing(app_db, note):
    req = _needs_info_request(app_db)
    before = len(_events(app_db, req))
    with pytest.raises(RequestError, match="หมายเหตุ"):
        requeue_request(app_db, req.id, account_for(app_db, "procurement"), note)
    app_db.expire_all()
    req = app_db.get(ItemRequest, req.id)
    assert req.status == "needs_info" and req.review_note == "ขอขนาด"
    assert len(_events(app_db, req)) == before


def test_the_queue_button_without_a_note_is_422(client, app_db):
    req = _needs_info_request(app_db)
    r = client.post(f"/queue/{req.id}/status", data={"new_status": "submitted", "note": " "})
    assert r.status_code == 422 and "หมายเหตุ" in r.text
    app_db.expire_all()
    assert app_db.get(ItemRequest, req.id).status == "needs_info"


def test_the_queue_button_with_a_note_requeues(client, app_db):
    req = _needs_info_request(app_db)
    before = len(_events(app_db, req))
    r = client.post(f"/queue/{req.id}/status", data={"new_status": "submitted", "note": NOTE})
    assert r.status_code == 200, r.text
    app_db.expire_all()
    req = app_db.get(ItemRequest, req.id)
    assert req.status == "submitted" and req.review_note is None
    new = _events(app_db, req)[before:]
    assert [(e.action, e.detail) for e in new] == [("submitted", NOTE)]


# --- 3. Q18: the button never touches the mail sender ------------------------------------------

def test_the_queue_button_never_calls_the_mail_sender(client, app_db):
    from app.main import app
    from app.services.mail import get_mail_sender

    calls: list[str] = []

    class Tripwire:
        def prepare(self) -> None:
            calls.append("prepare")
            raise AssertionError("no email for a requeue (Q18)")

        def send(self, message: object) -> None:
            calls.append("send")
            raise AssertionError("no email for a requeue (Q18)")

    app.dependency_overrides[get_mail_sender] = lambda: Tripwire()
    req = _needs_info_request(app_db)
    r = client.post(f"/queue/{req.id}/status", data={"new_status": "submitted", "note": NOTE})
    assert r.status_code == 200, r.text  # background tasks have run by now
    assert calls == []


# --- 4. No longer in Needs Info: 409 -----------------------------------------------------------------

def test_the_queue_button_on_a_request_no_longer_waiting_is_409(client, app_db):
    req = _needs_info_request(app_db)
    requeue_request(app_db, req.id, account_for(app_db, "procurement"), NOTE)
    before = len(_events(app_db, req))
    r = client.post(f"/queue/{req.id}/status", data={"new_status": "submitted", "note": "ซ้ำ"})
    assert r.status_code == 409 and "คำขอนี้ไม่ได้รอข้อมูลแล้ว" in r.text
    assert len(_events(app_db, req)) == before


# --- 5. The panel ------------------------------------------------------------------------------------

def test_the_panel_asks_for_a_note_on_requeue_only(client, app_db):
    req = _needs_info_request(app_db)
    page = client.get(f"/queue/{req.id}").text
    form = page.split("ผู้ขอส่งข้อมูลแล้ว รับเข้าคิวใหม่", 1)[0].rsplit("<form", 1)[1]
    assert 'name="note" required' in form
    assert 'value="rejected"' not in form  # rejecting from Needs Info: its own form
    assert 'value="rejected"' in page


# --- 6/7. Two threads, one claim ---------------------------------------------------------------------

def _file_db(tmp_path: Path, seeded_template: Engine) -> sessionmaker:
    url = f"sqlite:///{(tmp_path / 'requeue-race.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    src, dst = seeded_template.raw_connection(), engine.raw_connection()
    try:
        src.driver_connection.backup(dst.driver_connection)
    finally:
        src.close()
        dst.close()
    return sessionmaker(bind=engine, expire_on_commit=False)


Job = Callable[[Session], None]


def _race(monkeypatch: pytest.MonkeyPatch, factory: sessionmaker,
          jobs: dict[str, Job]) -> dict[str, object]:
    """Run each job in its own thread and session; the Barrier makes both
    reach the claim together. The loser's UPDATE waits on SQLite's write lock
    until the winner commits, or runs after it; either way it matches 0 rows."""
    gate = threading.Barrier(len(jobs))
    real_claim, real_dup = svc._claim_from_needs_info, svc._duplicate_line

    def claim_together(db: Session, request_id: int) -> ItemRequest:
        gate.wait(timeout=10)
        return real_claim(db, request_id)

    def slow_duplicates(*args: object, **kwargs: object) -> str | None:
        # Since STORY-009's closing review the Duplicate Check runs before the
        # claim, so this sleep no longer holds the claim; the Barrier above is
        # what makes the two collide.
        time.sleep(0.3)
        return real_dup(*args, **kwargs)

    monkeypatch.setattr(svc, "_claim_from_needs_info", claim_together)
    monkeypatch.setattr(svc, "_duplicate_line", slow_duplicates)
    results: dict[str, object] = {}

    def run(name: str, job: Job) -> None:
        with factory() as db:
            try:
                job(db)
                results[name] = "ok"
            except Exception as e:  # noqa: BLE001 - the test inspects it
                results[name] = e

    threads = [threading.Thread(target=run, args=(n, j)) for n, j in jobs.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def _resubmit(request_id: int, brand: str, reply: str) -> Job:
    def job(db: Session) -> None:
        req = db.get(ItemRequest, request_id)
        me = account_for(db, "requester", plant="APM")
        resubmit_request(db, request_id, me, reply=reply, code_system_id=req.code_system_id,
                         group_id=req.group_id, subgroup_id=req.subgroup_id,
                         item_name=req.base_name, brand=brand, search_name=req.search_name)
    return job


def _requeue(request_id: int, note: str) -> Job:
    def job(db: Session) -> None:
        requeue_request(db, request_id, account_for(db, "procurement"), note)
    return job


def _all_text(db: Session, request_id: int) -> str:
    db.expire_all()
    req = db.get(ItemRequest, request_id)
    cells = [str(v) for v in req.__dict__.values() if isinstance(v, str)]
    cells += [e.detail or "" for e in db.scalars(
        select(RequestEvent).where(RequestEvent.request_id == request_id))]
    return "\n".join(cells)


def _one_winner(results: dict[str, object]) -> tuple[str, str]:
    ok = [n for n, r in results.items() if r == "ok"]
    lost = [n for n, r in results.items() if isinstance(r, RequestConflict)]
    assert len(ok) == 1 and len(lost) == 1, results
    return ok[0], lost[0]


def test_two_resubmits_at_once_one_wins(tmp_path, seeded_template, monkeypatch):
    factory = _file_db(tmp_path, seeded_template)
    with factory() as db:
        request_id = _needs_info_request(db).id
        before = len(_events(db, db.get(ItemRequest, request_id)))
    marks = {"A": ("BRAND-A", "REPLY-A"), "B": ("BRAND-B", "REPLY-B")}
    results = _race(monkeypatch, factory, {n: _resubmit(request_id, *m) for n, m in marks.items()})
    winner, loser = _one_winner(results)
    with factory() as db:
        new = _events(db, db.get(ItemRequest, request_id))[before:]
        assert [e.action for e in new].count("submitted") == 1
        text = _all_text(db, request_id)
        assert db.get(ItemRequest, request_id).brand == marks[winner][0]
        assert marks[winner][1] in text
        assert marks[loser][0] not in text and marks[loser][1] not in text


def test_a_resubmit_and_the_queue_button_at_once_one_wins(tmp_path, seeded_template,
                                                          monkeypatch):
    factory = _file_db(tmp_path, seeded_template)
    with factory() as db:
        request_id = _needs_info_request(db).id
        before = len(_events(db, db.get(ItemRequest, request_id)))
    results = _race(monkeypatch, factory, {
        "resubmit": _resubmit(request_id, "BRAND-R", "REPLY-R"),
        "requeue": _requeue(request_id, "NOTE-Q"),
    })
    winner, loser = _one_winner(results)
    with factory() as db:
        new = _events(db, db.get(ItemRequest, request_id))[before:]
        assert [e.action for e in new].count("submitted") == 1
        text = _all_text(db, request_id)
        if loser == "resubmit":
            assert "BRAND-R" not in text and "REPLY-R" not in text
            assert "request_edited" not in [e.action for e in new]
            assert "NOTE-Q" in text
        else:
            assert "NOTE-Q" not in text
            assert "BRAND-R" in text and "REPLY-R" in text


# --- Code review (2026-10-16): the Role rule lives in the service too -------------------------------

def test_a_requester_cannot_requeue_even_through_the_service(app_db):
    req = _needs_info_request(app_db)
    before = len(_events(app_db, req))
    requester = account_for(app_db, "requester", plant="APM")  # the request's own Requester
    for call in (lambda: requeue_request(app_db, req.id, requester, NOTE),
                 lambda: change_status(app_db, req.id, new_status="submitted",
                                       account=requester, note=NOTE)):
        with pytest.raises(svc.RequestForbidden):
            call()
    app_db.expire_all()
    req = app_db.get(ItemRequest, req.id)
    assert req.status == "needs_info" and req.review_note == "ขอขนาด"
    assert len(_events(app_db, req)) == before
