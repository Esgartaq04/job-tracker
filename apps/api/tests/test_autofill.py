"""Phase 4b — what the extension's autofill puts where, and what it refuses to answer."""

from fastapi.testclient import TestClient

from src.schemas.autofill import Education, ResumeProfile

API = "/api/v1"

PROFILE = ResumeProfile(
    first_name="Esteven",
    last_name="Garcia",
    email="esteven@example.com",
    phone="+1 555 0100",
    city="Chicago",
    region="IL",
    country="United States",
    linkedin_url="https://www.linkedin.com/in/esteven",
    github_url="https://github.com/esteven",
    education=[Education(school="University of Illinois", degree="BS Computer Science")],
    skills=["Python", "Go"],
)


def field(id: str, label: str, kind: str = "text", **extra) -> dict:
    return {"id": id, "kind": kind, "label": label, **extra}


def plan(client: TestClient, fields: list[dict]) -> dict:
    response = client.post(
        f"{API}/autofill/map",
        json={
            "page_url": "https://boards.greenhouse.io/ramp/jobs/1",
            "fields": fields,
            "profile": PROFILE.model_dump(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def values(result: dict) -> dict:
    return {a["field_id"]: a.get("value") or a.get("attach") for a in result["assignments"]}


def needs(result: dict) -> dict:
    return {n["field_id"]: n["reason"] for n in result["needs_user"]}


def test_standard_fields_fill_without_any_ai(auth_client: TestClient):
    result = plan(
        auth_client,
        [
            field("0:1", "First Name", required=True),
            field("0:2", "Last Name", required=True),
            field("0:3", "Email", input_type="email"),
            field("0:4", "Phone"),
            field("0:5", "LinkedIn Profile"),
            field("0:6", "Website", autocomplete="url"),
            field("0:7", "", autocomplete="section-contact given-name", name="fn"),
            field("0:8", "Resume/CV", kind="file", file_role="resume", required=True),
        ],
    )
    assert values(result) == {
        "0:1": "Esteven",
        "0:2": "Garcia",
        "0:3": "esteven@example.com",
        "0:4": "+1 555 0100",
        "0:5": "https://www.linkedin.com/in/esteven",
        "0:7": "Esteven",
        "0:8": "resume",
    }
    assert result["used_ai"] is False
    assert {a["source"] for a in result["assignments"]} == {"rule"}


def test_sensitive_questions_are_always_handed_back(auth_client: TestClient, fake_ai):
    sensitive = [
        field(
            "1",
            "Are you legally authorized to work in the United States?",
            "radio",
            options=["Yes", "No"],
            required=True,
        ),
        field(
            "2",
            "Will you now or in the future require sponsorship?",
            "select",
            options=["Yes", "No"],
        ),
        field("3", "Gender", "select", options=["Male", "Female", "Decline to self-identify"]),
        field("4", "Veteran status", "select", options=["I am a veteran", "I am not"]),
        field("5", "What are your salary expectations?"),
        field("6", "I certify that the information above is true", "checkbox", options=["Yes"]),
    ]
    result = plan(auth_client, sensitive)

    assert result["assignments"] == []
    assert set(needs(result)) == {"1", "2", "3", "4", "5", "6"}
    assert set(needs(result).values()) == {"only you can answer this"}
    assert fake_ai.requests == [], "sensitive questions never even reach the model"


def test_the_model_fills_what_rules_cannot_and_is_checked(auth_client: TestClient, fake_ai):
    from src.services.autofill import _Answer, _Answers

    fake_ai.parsed(
        _Answers(
            answers=[
                _Answer(field_id="a", value="Bachelor's"),  # a real option
                _Answer(field_id="b", value="Expert"),  # not one of the options
                _Answer(field_id="zzz", value="hello"),  # not a field on the page
                _Answer(field_id="c", value=None),
            ]
        )
    )
    result = plan(
        auth_client,
        [
            field(
                "a",
                "Highest level of education",
                "select",
                options=["High school", "Bachelor's", "Master's"],
            ),
            field("b", "Python proficiency", "select", options=["Beginner", "Intermediate"]),
            field("c", "Years of Kubernetes experience", required=True),
            field("d", "Email"),
        ],
    )

    assert values(result) == {"d": "esteven@example.com", "a": "Bachelor's"}
    assert needs(result) == {"c": "not on your resume"}
    assert result["used_ai"] is True

    sent = fake_ai.requests[0]["messages"][0]["content"]
    assert '"field_id": "a"' in sent and '"field_id": "d"' not in sent, "only leftovers go"
    assert "esteven@example.com" in sent


def test_essay_questions_are_left_for_the_user(auth_client: TestClient):
    result = plan(
        auth_client,
        [field("q", "Why do you want to work at Ramp?", "textarea", required=True)],
    )
    assert needs(result) == {"q": "this wants your own words"}


def test_a_country_select_takes_its_own_spelling(auth_client: TestClient):
    result = plan(
        auth_client,
        [field("c", "Country", "select", options=["Canada", "United States", "Mexico"])],
    )
    assert values(result) == {"c": "United States"}


def test_reading_a_resume_returns_a_profile_and_stores_nothing(
    auth_client: TestClient, fake_ai, db_session
):
    from src.models import Document

    fake_ai.parsed(PROFILE)
    response = auth_client.post(
        f"{API}/autofill/profile",
        files={"resume": ("resume.pdf", b"%PDF-1.7 resume", "application/pdf")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["email"] == "esteven@example.com"
    assert fake_ai.requests[0]["messages"][0]["content"][0]["type"] == "document"
    assert db_session.query(Document).count() == 0


def test_reading_a_resume_without_a_key_says_why(auth_client: TestClient):
    response = auth_client.post(
        f"{API}/autofill/profile",
        files={"resume": ("resume.pdf", b"%PDF-1.7 resume", "application/pdf")},
    )
    assert response.status_code == 503
