"""CSV import: forgiving about headers, strict about identity."""

from fastapi.testclient import TestClient

API = "/api/v1"


def upload(client: TestClient, csv_text: str) -> dict:
    response = client.post(
        f"{API}/applications/import",
        files={"file": ("applications.csv", csv_text.encode(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_typical_spreadsheet_lands_on_the_board(auth_client: TestClient):
    report = upload(
        auth_client,
        "Company,Role,Link,Status,Date Applied,Location,Tags\n"
        "Stripe,SWE Intern,https://boards.greenhouse.io/stripe/jobs/1,Applied,2026-06-01,NYC,referral\n"
        "Datadog,Backend Intern,https://example.com/dd,Interview,06/15/2026,Remote,\n",
    )
    assert report["created"] == 2
    assert report["summary"] == "2 imported"

    board = auth_client.get(f"{API}/applications/board").json()
    by_status = {column["status"]: column["items"] for column in board["columns"]}
    assert [item["company"] for item in by_status["applied"]] == ["Stripe"]
    assert [item["company"] for item in by_status["interview"]] == ["Datadog"]
    assert by_status["applied"][0]["applied_at"].startswith("2026-06-01")
    assert [tag["name"] for tag in by_status["applied"][0]["tags"]] == ["referral"]


def test_headers_do_not_have_to_match_ours(auth_client: TestClient):
    """Every spreadsheet template names these columns differently."""
    report = upload(
        auth_client,
        "employer,position,job url,stage\nRamp,Backend Intern,https://jobs.lever.co/ramp/x,offer\n",
    )
    assert report["created"] == 1
    board = auth_client.get(f"{API}/applications/board").json()
    offers = next(column for column in board["columns"] if column["status"] == "offer")
    assert offers["items"][0]["title"] == "Backend Intern"


def test_free_text_statuses_are_understood(auth_client: TestClient):
    upload(
        auth_client,
        "company,title,status\n"
        "A,One,Online Assessment\n"
        "B,Two,Recruiter Screen\n"
        "C,Three,Final Round\n"
        "D,Four,No response\n"
        "E,Five,something nobody recognises\n",
    )
    board = auth_client.get(f"{API}/applications/board").json()
    landed = {
        column["status"]: [item["company"] for item in column["items"]]
        for column in board["columns"]
        if column["count"]
    }
    assert landed["oa"] == ["A"]
    assert landed["phone_screen"] == ["B"]
    assert landed["final"] == ["C"]
    assert landed["ghosted"] == ["D"]
    # An unrecognised status is saved rather than dropped.
    assert landed["saved"] == ["E"]


def test_an_applied_date_outranks_a_saved_status(auth_client: TestClient):
    """If the row says when you applied, it's an application whatever the status says."""
    upload(auth_client, "company,title,status,date applied\nStripe,SWE,Saved,2026-05-04\n")
    board = auth_client.get(f"{API}/applications/board").json()
    applied = next(column for column in board["columns"] if column["status"] == "applied")
    assert applied["count"] == 1


def test_rows_without_an_identity_are_reported_not_invented(auth_client: TestClient):
    report = upload(
        auth_client,
        "company,title,url\nStripe,SWE Intern,https://example.com/1\n,,https://example.com/2\n",
    )
    assert report["created"] == 1
    assert report["skipped"] == [{"line": 3, "reason": "no company or title"}]
    assert "1 skipped" in report["summary"]


def test_importing_the_same_file_twice_does_not_duplicate(auth_client: TestClient):
    csv_text = (
        "company,title,url\n"
        "Stripe,SWE Intern,https://boards.greenhouse.io/stripe/jobs/1\n"
        "Datadog,Backend Intern,\n"
    )
    first = upload(auth_client, csv_text)
    second = upload(auth_client, csv_text)

    assert first["created"] == 2
    # Matched by canonical URL where there is one, by company+title where there isn't.
    assert second["created"] == 0
    assert second["duplicates"] == 2


def test_a_url_that_is_already_tracked_is_recognised(auth_client: TestClient):
    auth_client.post(
        f"{API}/applications",
        json={"company": "Stripe", "title": "SWE", "source_url": "https://example.com/jobs/1"},
    )
    report = upload(
        auth_client,
        "company,title,url\nStripe,SWE Intern,https://example.com/jobs/1?utm_source=sheet\n",
    )
    assert report["duplicates"] == 1
    assert report["created"] == 0


def test_columns_we_could_not_map_are_named(auth_client: TestClient):
    """So the user can see why their 'Referral Contact' column didn't come through."""
    report = upload(auth_client, "company,title,Referral Contact,Salary Band\nStripe,SWE,Ana,L3\n")
    assert report["unmapped_columns"] == ["Referral Contact", "Salary Band"]


def test_a_malformed_url_does_not_lose_the_row(auth_client: TestClient):
    report = upload(auth_client, "company,title,url\nStripe,SWE Intern,not a url at all\n")
    assert report["created"] == 1


def test_an_empty_file_is_rejected_clearly(auth_client: TestClient):
    response = auth_client.post(
        f"{API}/applications/import", files={"file": ("empty.csv", b"", "text/csv")}
    )
    assert response.status_code == 422
    assert "empty" in response.json()["detail"]


def test_our_own_export_round_trips(auth_client: TestClient):
    """The export the Table view writes must be importable — otherwise "export" is a
    dead end rather than a backup."""
    auth_client.post(
        f"{API}/applications",
        json={
            "company": "Snowflake",
            "title": "Data Intern",
            "source_url": "https://example.com/snow",
            "status": "applied",
        },
    )
    rows = auth_client.get(f"{API}/applications").json()["items"]
    header = "company,title,status,location,saved_at,applied_at,url"
    exported = "\n".join(
        [header]
        + [
            ",".join(
                f'"{(row.get(field) or "")}"'
                for field in ("company", "title", "status", "location", "saved_at", "applied_at")
            )
            + f',"{row["source_url"]}"'
            for row in rows
        ]
    )

    # Re-importing it into a second account reproduces the same board.
    other = auth_client.post(
        f"{API}/auth/register", json={"email": "other@x.com", "password": "correct-horse-9"}
    ).json()["access_token"]
    response = auth_client.post(
        f"{API}/applications/import",
        files={"file": ("export.csv", exported.encode(), "text/csv")},
        headers={"Authorization": f"Bearer {other}"},
    )
    assert response.json()["created"] == 1

    board = auth_client.get(
        f"{API}/applications/board", headers={"Authorization": f"Bearer {other}"}
    ).json()
    applied = next(column for column in board["columns"] if column["status"] == "applied")
    assert applied["items"][0]["company"] == "Snowflake"
