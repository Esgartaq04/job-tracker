"""End-to-end API behaviour: auth scoping, the board, moves, and transition side effects."""

import uuid

from fastapi.testclient import TestClient

API = "/api/v1"


def create(client: TestClient, **overrides) -> dict:
    payload = {"company": "Datadog", "title": "Backend Intern", **overrides}
    response = client.post(f"{API}/applications", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_registration_is_required(client: TestClient):
    assert client.get(f"{API}/applications/board").status_code == 401


def test_login_rejects_a_wrong_password(client: TestClient):
    client.post(f"{API}/auth/register", json={"email": "a@b.com", "password": "correct-horse-1"})
    response = client.post(
        f"{API}/auth/login", json={"email": "a@b.com", "password": "wrong-horse-1"}
    )
    assert response.status_code == 401


def test_duplicate_registration_is_rejected(client: TestClient):
    body = {"email": "a@b.com", "password": "correct-horse-1"}
    assert client.post(f"{API}/auth/register", json=body).status_code == 201
    assert client.post(f"{API}/auth/register", json=body).status_code == 409


def test_manual_create_lands_in_saved_and_starts_a_timeline(auth_client: TestClient):
    application = create(auth_client)
    assert application["status"] == "saved"
    assert application["applied_at"] is None
    assert application["days_since_saved"] == 0
    assert [event["to_status"] for event in application["events"]] == ["saved"]


def test_board_returns_every_column_in_pipeline_order(auth_client: TestClient):
    create(auth_client)
    board = auth_client.get(f"{API}/applications/board").json()
    statuses = [column["status"] for column in board["columns"]]
    assert statuses[:3] == ["saved", "applied", "oa"]
    assert statuses[-3:] == ["rejected", "withdrawn", "ghosted"]
    saved = next(column for column in board["columns"] if column["status"] == "saved")
    assert saved["count"] == 1


def test_moving_to_applied_stamps_applied_at_once(auth_client: TestClient):
    application = create(auth_client)

    moved = auth_client.patch(
        f"{API}/applications/{application['id']}/move", json={"to_status": "applied"}
    ).json()
    assert moved["status"] == "applied"
    assert moved["applied_at"] is not None
    first_stamp = moved["applied_at"]

    # Bouncing through another column must not rewrite the original apply date.
    auth_client.patch(f"{API}/applications/{application['id']}/move", json={"to_status": "oa"})
    back = auth_client.patch(
        f"{API}/applications/{application['id']}/move", json={"to_status": "applied"}
    ).json()
    assert back["applied_at"] == first_stamp


def test_rejection_stamps_closed_at_and_reopening_clears_it(auth_client: TestClient):
    application = create(auth_client)
    rejected = auth_client.patch(
        f"{API}/applications/{application['id']}/move", json={"to_status": "rejected"}
    ).json()
    assert rejected["closed_at"] is not None

    reopened = auth_client.patch(
        f"{API}/applications/{application['id']}/move", json={"to_status": "interview"}
    ).json()
    assert reopened["closed_at"] is None


def test_every_transition_is_appended_to_the_timeline(auth_client: TestClient):
    application = create(auth_client)
    for status_ in ("applied", "oa", "interview", "offer"):
        auth_client.patch(
            f"{API}/applications/{application['id']}/move", json={"to_status": status_}
        )

    events = auth_client.get(f"{API}/applications/{application['id']}/events").json()
    assert [event["to_status"] for event in events] == [
        "saved",
        "applied",
        "oa",
        "interview",
        "offer",
    ]
    assert events[1]["from_status"] == "saved"


def test_a_no_op_move_writes_no_event(auth_client: TestClient):
    application = create(auth_client)
    auth_client.patch(f"{API}/applications/{application['id']}/move", json={"to_status": "saved"})
    events = auth_client.get(f"{API}/applications/{application['id']}/events").json()
    assert len(events) == 1


def test_reordering_within_a_column_uses_neighbour_ids(auth_client: TestClient):
    first = create(auth_client, title="First")
    second = create(auth_client, title="Second")
    third = create(auth_client, title="Third")

    def order() -> list[str]:
        board = auth_client.get(f"{API}/applications/board").json()
        saved = next(c for c in board["columns"] if c["status"] == "saved")
        return [item["title"] for item in saved["items"]]

    # Cards are prepended, so the newest is on top.
    assert order() == ["Third", "Second", "First"]

    auth_client.patch(
        f"{API}/applications/{third['id']}/move",
        json={"to_status": "saved", "before_id": second["id"], "after_id": first["id"]},
    )
    assert order() == ["Second", "Third", "First"]


def test_archiving_hides_the_card_and_frees_the_url(auth_client: TestClient):
    application = create(auth_client, source_url="https://example.com/jobs/1")
    assert auth_client.delete(f"{API}/applications/{application['id']}").status_code == 204

    board = auth_client.get(f"{API}/applications/board").json()
    assert sum(column["count"] for column in board["columns"]) == 0

    # The partial unique index only covers live rows, so the URL can be re-tracked.
    again = create(auth_client, source_url="https://example.com/jobs/1")
    assert again["id"] != application["id"]


def test_re_adding_a_tracked_url_is_a_conflict(auth_client: TestClient):
    create(auth_client, source_url="https://example.com/jobs/7")
    response = auth_client.post(
        f"{API}/applications", json={"source_url": "https://example.com/jobs/7?utm_source=x"}
    )
    assert response.status_code == 409


def test_user_edits_shadow_the_extracted_description(auth_client: TestClient):
    application = create(auth_client)
    updated = auth_client.patch(
        f"{API}/applications/{application['id']}",
        json={"description_user": "My own notes on the role"},
    ).json()
    assert updated["description"] == "My own notes on the role"
    assert updated["description_raw"] is None


def test_notes_are_appended_with_a_date(auth_client: TestClient):
    application = create(auth_client)
    auth_client.post(f"{API}/applications/{application['id']}/notes", json={"text": "Referred"})
    result = auth_client.post(
        f"{API}/applications/{application['id']}/notes", json={"text": "Followed up"}
    ).json()
    assert "Referred" in result["notes"] and "Followed up" in result["notes"]


def test_tags_are_created_on_demand_and_reused(auth_client: TestClient):
    create(auth_client, tags=["referral", "summer-2027"])
    create(auth_client, tags=["referral"])
    tags = auth_client.get(f"{API}/tags").json()
    assert sorted(tag["name"] for tag in tags) == ["referral", "summer-2027"]


def test_search_matches_company_and_description(auth_client: TestClient):
    create(auth_client, company="Snowflake", title="Data Intern")
    create(auth_client, company="Citadel", title="Quant Intern")

    hits = auth_client.get(f"{API}/search", params={"q": "snow"}).json()
    assert [hit["company"] for hit in hits] == ["Snowflake"]


def test_applications_are_scoped_to_their_owner(client: TestClient):
    first = client.post(
        f"{API}/auth/register", json={"email": "one@x.com", "password": "correct-horse-1"}
    ).json()["access_token"]
    second = client.post(
        f"{API}/auth/register", json={"email": "two@x.com", "password": "correct-horse-2"}
    ).json()["access_token"]

    created = client.post(
        f"{API}/applications",
        json={"company": "Stripe", "title": "SWE"},
        headers={"Authorization": f"Bearer {first}"},
    ).json()

    response = client.get(
        f"{API}/applications/{created['id']}", headers={"Authorization": f"Bearer {second}"}
    )
    assert response.status_code == 404


def test_pasting_a_url_returns_a_provisional_card_immediately(
    auth_client: TestClient, enqueued: list
):
    response = auth_client.post(
        f"{API}/ingest", json={"url": "https://boards.greenhouse.io/stripe/jobs/1"}
    )
    assert response.status_code == 202
    body = response.json()
    assert body["ingest_status"] == "pending"
    assert body["duplicate"] is False

    # The card is on the board before ingestion has resolved.
    board = auth_client.get(f"{API}/applications/board").json()
    saved = next(column for column in board["columns"] if column["status"] == "saved")
    assert saved["count"] == 1
    assert saved["items"][0]["company"] == "Stripe"  # guessed from the URL

    # ...and extraction was handed to the queue rather than run in the request.
    assert enqueued == [uuid.UUID(body["application_id"])]


def test_pasting_a_known_url_focuses_the_existing_card(auth_client: TestClient, enqueued: list):
    first = auth_client.post(f"{API}/ingest", json={"url": "https://example.com/jobs/42"}).json()
    second = auth_client.post(
        f"{API}/ingest", json={"url": "https://example.com/jobs/42?utm_source=newsletter"}
    ).json()

    assert second["duplicate"] is True
    assert second["application_id"] == first["application_id"]
    # A duplicate must not queue a second extraction of the same posting.
    assert len(enqueued) == 1


def test_paste_and_mark_as_applied_sets_both_timestamps(auth_client: TestClient):
    response = auth_client.post(
        f"{API}/ingest",
        json={"url": "https://example.com/jobs/9", "mark_as_applied": True},
    ).json()
    application = auth_client.get(f"{API}/applications/{response['application_id']}").json()
    assert application["status"] == "applied"
    assert application["applied_at"] is not None
    assert application["saved_at"] is not None


def test_manual_text_fallback_is_always_available(auth_client: TestClient):
    """LinkedIn blocks scraping; the user pastes the description instead."""
    response = auth_client.post(
        f"{API}/ingest/from-text",
        json={
            "url": "https://www.linkedin.com/jobs/view/123",
            "text": "## About the role\nYou'll build the ingestion pipeline.",
            "company": "Datadog",
            "title": "Backend Intern",
        },
    )
    assert response.status_code == 200
    application = response.json()
    assert application["company"] == "Datadog"
    assert "ingestion pipeline" in application["description"]
    assert application["extraction_meta"]["manual"] is True


def test_extension_dom_path_parses_without_fetching(auth_client: TestClient):
    html = """
    <html><head><script type="application/ld+json">
    {"@type":"JobPosting","title":"SWE Intern","hiringOrganization":{"name":"Cisco"},
     "description":"<p>Work on routing.</p>"}
    </script></head><body></body></html>
    """
    response = auth_client.post(
        f"{API}/ingest/from-dom",
        json={"url": "https://www.linkedin.com/jobs/view/999", "html": html},
    )
    assert response.status_code == 200
    application = response.json()
    assert application["company"] == "Cisco"
    assert application["title"] == "SWE Intern"
    assert application["ingest_status"] == "ok"


def test_funnel_counts_stages_ever_reached(auth_client: TestClient):
    reached_offer = create(auth_client, title="A")
    rejected = create(auth_client, title="B")
    create(auth_client, title="C")  # still saved

    for status_ in ("applied", "interview", "offer"):
        auth_client.patch(
            f"{API}/applications/{reached_offer['id']}/move", json={"to_status": status_}
        )
    for status_ in ("applied", "rejected"):
        auth_client.patch(f"{API}/applications/{rejected['id']}/move", json={"to_status": status_})

    funnel = auth_client.get(f"{API}/stats/funnel").json()
    stages = {stage["status"]: stage["reached"] for stage in funnel["stages"]}
    assert funnel["total"] == 3
    assert stages["applied"] == 2
    assert stages["interview"] == 1
    assert stages["offer"] == 1
    assert funnel["response_rate"] == 1.0  # both applications heard back


def test_velocity_buckets_by_week(auth_client: TestClient):
    application = create(auth_client)
    auth_client.patch(f"{API}/applications/{application['id']}/move", json={"to_status": "applied"})

    velocity = auth_client.get(f"{API}/stats/velocity", params={"weeks": 4}).json()
    assert len(velocity["weekly"]) >= 4
    assert sum(bucket["saved"] for bucket in velocity["weekly"]) == 1
    assert sum(bucket["applied"] for bucket in velocity["weekly"]) == 1
    assert velocity["stale_count"] == 0


def test_extension_hints_fill_gaps_the_tiers_left(auth_client: TestClient):
    """LinkedIn markup defeats the readability pass, so the extension also sends what
    it could read off the rendered page. Hints fill blanks; they never overwrite."""
    response = auth_client.post(
        f"{API}/ingest/from-dom",
        json={
            "url": "https://www.linkedin.com/jobs/view/4001",
            "html": "<html><body><div>Apply now</div></body></html>",
            "hints": {
                "title": "Software Engineer Intern",
                "company": "Ramp",
                "location": "New York, NY",
            },
            "fallback_text": "About the job\n" + ("You will own the ledger service. " * 12),
        },
    )
    assert response.status_code == 200
    application = response.json()
    assert application["company"] == "Ramp"
    assert application["title"] == "Software Engineer Intern"
    assert application["location"] == "New York, NY"
    assert "ledger service" in application["description"]
    # Selector-scraped fields stay flagged for verification.
    assert application["extraction_meta"]["needs_verification"] is True


def test_a_real_extraction_outranks_extension_hints(auth_client: TestClient):
    """A stale selector must never overwrite what the page actually published."""
    html = """
    <html><head><script type="application/ld+json">
    {"@type":"JobPosting","title":"Backend Engineering Intern",
     "hiringOrganization":{"name":"Datadog"},
     "description":"<p>Work on the data ingestion pipeline.</p>"}
    </script></head><body></body></html>
    """
    response = auth_client.post(
        f"{API}/ingest/from-dom",
        json={
            "url": "https://www.linkedin.com/jobs/view/4002",
            "html": html,
            "hints": {"title": "Sign in to view", "company": "LinkedIn"},
        },
    )
    application = response.json()
    assert application["company"] == "Datadog"
    assert application["title"] == "Backend Engineering Intern"
