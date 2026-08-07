"""What needs attention, and — just as importantly — what doesn't."""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient

from src.models.util import utcnow
from src.services import reminders as reminder_service

API = "/api/v1"


def create(client: TestClient, **overrides) -> dict:
    payload = {"company": "Datadog", "title": "Backend Intern", **overrides}
    response = client.post(f"{API}/applications", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def iso(days: int) -> str:
    return (utcnow() + timedelta(days=days)).isoformat()


def age(db_session, application_id: str, *, days: int) -> None:
    """Backdate a card and its timeline together — a card saved N days ago also had
    its first status event N days ago, and staleness reads both."""
    from src.models import Application, StatusEvent

    row = db_session.get(Application, uuid.UUID(application_id))
    when = utcnow() - timedelta(days=days)
    row.saved_at = when
    row.updated_at = when
    for event in db_session.query(StatusEvent).filter_by(application_id=row.id):
        event.occurred_at = when
    db_session.commit()


def set_due(db_session, application_id: str, *, days: int) -> None:
    from src.models import Application

    row = db_session.get(Application, uuid.UUID(application_id))
    row.next_action_at = utcnow() + timedelta(days=days)
    db_session.commit()


def test_an_empty_board_needs_no_attention(auth_client: TestClient):
    body = auth_client.get(f"{API}/reminders").json()
    assert body["count"] == 0
    assert body["summary"] == "Nothing needs attention"


def test_overdue_follow_ups_come_first(auth_client: TestClient):
    overdue = create(auth_client, company="Stripe")
    upcoming = create(auth_client, company="Ramp")
    auth_client.patch(f"{API}/applications/{overdue['id']}", json={"next_action_at": iso(-3)})
    auth_client.patch(f"{API}/applications/{upcoming['id']}", json={"next_action_at": iso(2)})

    body = auth_client.get(f"{API}/reminders").json()
    assert [item["application"]["company"] for item in body["items"]] == ["Stripe", "Ramp"]
    assert body["items"][0]["kind"] == "overdue"
    assert body["items"][0]["days"] == -3
    assert body["items"][0]["reason"] == "Follow-up was due 3d ago"
    assert body["items"][1]["kind"] == "upcoming"
    assert "1 overdue" in body["summary"]


def test_follow_ups_past_the_horizon_are_not_noise(auth_client: TestClient):
    application = create(auth_client)
    auth_client.patch(f"{API}/applications/{application['id']}", json={"next_action_at": iso(30)})

    assert auth_client.get(f"{API}/reminders").json()["count"] == 0
    # ...unless you ask to look that far ahead.
    assert auth_client.get(f"{API}/reminders", params={"look_ahead": 45}).json()["count"] == 1


def test_a_quiet_card_is_reported_as_stale(auth_client: TestClient, db_session):
    application = create(auth_client)
    age(db_session, application["id"], days=20)

    body = auth_client.get(f"{API}/reminders").json()
    assert body["count"] == 1
    assert body["items"][0]["kind"] == "stale"
    assert "No movement in 20d" == body["items"][0]["reason"]


def test_a_card_with_a_plan_is_not_also_nagged_about_silence(auth_client: TestClient, db_session):
    """The user already said what they intend to do; reporting it twice is noise."""
    application = create(auth_client)
    age(db_session, application["id"], days=40)
    auth_client.patch(f"{API}/applications/{application['id']}", json={"next_action_at": iso(3)})

    body = auth_client.get(f"{API}/reminders").json()
    assert [item["kind"] for item in body["items"]] == ["upcoming"]


def test_closed_applications_never_ask_for_attention(auth_client: TestClient, db_session):
    application = create(auth_client)
    auth_client.patch(
        f"{API}/applications/{application['id']}/move", json={"to_status": "rejected"}
    )

    age(db_session, application["id"], days=90)
    set_due(db_session, application["id"], days=-5)

    assert auth_client.get(f"{API}/reminders").json()["count"] == 0


def test_the_digest_reads_like_a_sentence():
    assert reminder_service.digest([]) == "Nothing needs attention"


def test_notifications_reach_a_connected_browser(auth_client: TestClient, db_session, monkeypatch):
    """The sweep pushes over SSE; email stays behind a flag until a provider exists."""
    from src.models import User
    from src.services import notify

    published: list[tuple] = []
    monkeypatch.setattr(
        notify.events, "publish", lambda user_id, kind, data: published.append((kind, data))
    )

    application = create(auth_client)
    set_due(db_session, application["id"], days=-1)
    published.clear()  # drop the application.created event the setup emitted

    user = db_session.query(User).filter_by(email="esteven@example.com").one()
    found = reminder_service.collect(db_session, user.id)
    notify.notify_user(user.id, user.email, found)

    assert [kind for kind, _ in published] == ["reminder.due"]
    payload = published[0][1]
    assert payload["count"] == 1
    assert payload["items"][0]["kind"] == "overdue"
    assert "1 overdue" in payload["summary"]


def test_the_email_digest_lists_every_reminder(auth_client: TestClient, db_session):
    from src.models import User
    from src.services.notify import render_digest

    for company, offset in (("Stripe", -2), ("Ramp", 0)):
        created = create(auth_client, company=company)
        set_due(db_session, created["id"], days=offset)

    user = db_session.query(User).filter_by(email="esteven@example.com").one()
    subject, body = render_digest(reminder_service.collect(db_session, user.id))

    assert "1 overdue" in subject and "1 due today" in subject
    assert "Stripe" in body and "Ramp" in body


class TestSweepEndpoint:
    """The sweep endpoint is what replaces the arq cron when there's no Redis to run a
    worker, so a scheduler can nudge everyone once a day."""

    def test_it_is_invisible_until_a_secret_is_configured(self, auth_client: TestClient):
        # Default settings have no secret — the route must not advertise itself.
        assert auth_client.post(f"{API}/reminders/sweep").status_code == 404
        assert (
            auth_client.post(
                f"{API}/reminders/sweep", headers={"x-sweep-secret": "anything"}
            ).status_code
            == 404
        )

    def test_a_wrong_secret_is_a_404_not_a_403(self, auth_client: TestClient, monkeypatch):
        """A 403 would confirm the endpoint exists and that the secret is worth guessing."""
        from src.routers import reminders as router

        monkeypatch.setattr(router.settings, "sweep_secret", "s3cret", raising=False)
        response = auth_client.post(f"{API}/reminders/sweep", headers={"x-sweep-secret": "wrong"})
        assert response.status_code == 404

    def test_the_right_secret_runs_the_same_sweep_the_worker_would(
        self, auth_client: TestClient, db_session, monkeypatch
    ):
        from src.routers import reminders as router
        from src.services import notify

        notified: list[tuple] = []
        monkeypatch.setattr(
            notify, "notify_user", lambda user_id, email, found: notified.append((email, found))
        )
        monkeypatch.setattr(router.settings, "sweep_secret", "s3cret", raising=False)

        overdue = create(auth_client, company="Stripe")
        set_due(db_session, overdue["id"], days=-3)

        response = auth_client.post(f"{API}/reminders/sweep", headers={"x-sweep-secret": "s3cret"})
        assert response.status_code == 200
        assert response.json() == {"users": 1, "notified": 1, "reminders": 1}

        assert len(notified) == 1
        email, found = notified[0]
        assert email == "esteven@example.com"
        assert found[0].kind is reminder_service.ReminderKind.overdue

    def test_a_user_with_nothing_pending_is_not_nagged(self, auth_client: TestClient, monkeypatch):
        from src.routers import reminders as router
        from src.services import notify

        notified: list[tuple] = []
        monkeypatch.setattr(
            notify, "notify_user", lambda user_id, email, found: notified.append((email, found))
        )
        monkeypatch.setattr(router.settings, "sweep_secret", "s3cret", raising=False)

        create(auth_client, company="Datadog")  # fresh card, no due date

        response = auth_client.post(f"{API}/reminders/sweep", headers={"x-sweep-secret": "s3cret"})
        assert response.json() == {"users": 1, "notified": 0, "reminders": 0}
        assert notified == []
