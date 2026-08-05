"""Extraction tiers: JSON-LD (T0), ATS adapters (T1), generic HTML (T2)."""

import httpx
import pytest
import respx

from src.services.ingestion import pipeline
from src.services.ingestion.adapters import find_adapter
from src.services.ingestion.adapters.greenhouse import GreenhouseAdapter
from src.services.ingestion.adapters.lever import LeverAdapter
from src.services.ingestion.tiers import generic, jsonld

JSON_LD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "title":"Backend Engineering Intern",
 "hiringOrganization":{"@type":"Organization","name":"Datadog"},
 "datePosted":"2026-07-21",
 "employmentType":"INTERN",
 "jobLocation":{"@type":"Place","address":{"addressLocality":"New York","addressRegion":"NY"}},
 "baseSalary":{"@type":"MonetaryAmount","currency":"USD",
   "value":{"@type":"QuantitativeValue","minValue":45,"maxValue":55,"unitText":"HOUR"}},
 "description":"<p>You'll work on the data ingestion pipeline.</p><ul><li>Go</li></ul>"}
</script></head><body><p>chrome</p></body></html>
"""


def test_jsonld_tier_reads_a_schema_org_posting():
    posting = jsonld.extract(JSON_LD_PAGE)
    assert posting is not None
    assert posting.company == "Datadog"
    assert posting.title == "Backend Engineering Intern"
    assert posting.location == "New York, NY"
    assert posting.employment_type == "internship"
    assert posting.salary_min == 45
    assert posting.salary_period == "hourly"
    assert "data ingestion" in posting.description_markdown
    assert posting.posted_at.year == 2026


def test_jsonld_tier_returns_nothing_on_a_page_without_a_posting():
    assert jsonld.extract("<html><body>No structured data here.</body></html>") is None


def test_generic_tier_falls_back_to_og_metadata():
    html = """
    <html><head>
      <meta property="og:title" content="ML Intern at Nvidia">
      <meta property="og:site_name" content="Nvidia Careers">
    </head><body><main><p>%s</p></main></body></html>
    """ % ("We are looking for an ML intern to work on CUDA kernels. " * 12)

    posting = generic.extract(html, "https://nvidia.com/careers/1")
    assert posting is not None
    assert posting.title == "ML Intern"
    assert posting.employment_type == "internship"
    assert "CUDA" in posting.description_markdown
    # Metadata scraping is a guess; the UI marks sub-0.6 fields for verification.
    assert posting.confidence < 0.6


def test_generic_tier_flags_a_content_free_page_as_low_confidence():
    posting = generic.extract(
        "<html><head><title>Careers</title></head><body>Accept cookies</body></html>",
        "https://example.com/careers",
    )
    assert posting is None or posting.confidence <= 0.3


@pytest.mark.parametrize(
    ("url", "vendor"),
    [
        ("https://boards.greenhouse.io/stripe/jobs/4512345", "greenhouse"),
        ("https://jobs.lever.co/ramp/1a2b3c4d-5e6f-7890-abcd-ef1234567890", "lever"),
        (
            "https://jobs.ashbyhq.com/linear/1a2b3c4d-5e6f-7890-abcd-ef1234567890",
            "ashby",
        ),
        ("https://jobs.smartrecruiters.com/Company/743999123456789", "smartrecruiters"),
        ("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternal/job/US/SWE_JR123", "workday"),
        ("https://example.com/careers/1", None),
    ],
)
def test_adapter_routing(url, vendor):
    adapter = find_adapter(url)
    assert (adapter.vendor if adapter else None) == vendor


@respx.mock
def test_greenhouse_adapter_uses_the_json_api():
    respx.get("https://boards-api.greenhouse.io/v1/boards/stripe/jobs/4512345").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 4512345,
                "internal_job_id": 99,
                "title": "SWE Intern",
                "company_name": "Stripe",
                "location": {"name": "New York, NY"},
                "first_published": "2026-06-01T00:00:00-04:00",
                "content": "&lt;p&gt;Build payments infrastructure.&lt;/p&gt;",
            },
        )
    )

    posting = GreenhouseAdapter().fetch("https://boards.greenhouse.io/stripe/jobs/4512345")
    assert posting.company == "Stripe"
    assert posting.title == "SWE Intern"
    assert posting.employment_type == "internship"
    assert posting.req_id == "99"
    assert "payments infrastructure" in posting.description_markdown


@respx.mock
def test_lever_adapter_merges_description_sections():
    posting_id = "1a2b3c4d-5e6f-7890-abcd-ef1234567890"
    respx.get(f"https://api.lever.co/v0/postings/ramp/{posting_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "text": "Software Engineer, Backend",
                "categories": {"location": "Remote (US)", "commitment": "Full-time"},
                "descriptionHtml": "<p>Own the ledger service.</p>",
                "lists": [{"text": "Requirements", "content": "<ul><li>Go</li></ul>"}],
                "workplaceType": "remote",
                "createdAt": 1770000000000,
            },
        )
    )

    posting = LeverAdapter().fetch(f"https://jobs.lever.co/ramp/{posting_id}")
    assert posting.company == "Ramp"
    assert posting.is_remote is True
    assert posting.employment_type == "full_time"
    assert "ledger service" in posting.description_markdown
    assert "Requirements" in posting.description_markdown


@respx.mock
def test_pipeline_prefers_the_adapter_and_never_fetches_the_page():
    page = respx.get("https://boards.greenhouse.io/stripe/jobs/4512345")
    respx.get("https://boards-api.greenhouse.io/v1/boards/stripe/jobs/4512345").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 4512345,
                "title": "SWE Intern",
                "company_name": "Stripe",
                "location": {"name": "NYC"},
                "content": "&lt;p&gt;Payments.&lt;/p&gt;",
            },
        )
    )

    outcome = pipeline.run_pipeline("https://boards.greenhouse.io/stripe/jobs/4512345?gh_src=x")
    assert outcome.tier_succeeded == "ats:greenhouse"
    assert outcome.ats_vendor == "greenhouse"
    assert outcome.posting.company == "Stripe"
    assert not page.called


@respx.mock
def test_pipeline_falls_through_to_jsonld_on_an_unknown_host():
    respx.get("https://example.com/careers/1").mock(
        return_value=httpx.Response(200, html=JSON_LD_PAGE, headers={"content-type": "text/html"})
    )

    outcome = pipeline.run_pipeline("https://example.com/careers/1")
    assert outcome.tier_succeeded == "jsonld"
    assert outcome.posting.company == "Datadog"
    assert outcome.status.value == "ok"


@respx.mock
def test_a_dead_posting_still_produces_a_usable_record():
    respx.get("https://example.com/careers/gone").mock(
        return_value=httpx.Response(404, text="gone")
    )

    outcome = pipeline.run_pipeline("https://example.com/careers/gone")
    assert outcome.posting is None
    assert outcome.status.value == "failed"
    assert "404" in outcome.error


def test_manual_paste_short_circuits_every_tier():
    outcome = pipeline.run_pipeline(
        "https://linkedin.com/jobs/view/1", text="## About the role\nYou will..."
    )
    assert outcome.tier_succeeded == "manual"
    assert outcome.posting.description_markdown.startswith("## About the role")


def test_generic_tier_reads_linkedins_title_format():
    """"<Company> hiring <Title> in <Location>" carries all three fields."""
    html = """
    <html><head><title>Ramp hiring Software Engineer Intern in New York, NY | LinkedIn</title>
    </head><body><main><p>%s</p></main></body></html>
    """ % ("You will own the ledger service. " * 20)

    posting = generic.extract(html, "https://www.linkedin.com/jobs/view/4001")
    assert posting.company == "Ramp"
    assert posting.title == "Software Engineer Intern"
    assert posting.location == "New York, NY"


def test_a_job_board_never_becomes_the_employer():
    """The site's own brand is not the company that's hiring."""
    html = """
    <html><head>
      <meta property="og:site_name" content="LinkedIn">
      <meta property="og:title" content="Backend Intern | LinkedIn">
    </head><body><main><p>%s</p></main></body></html>
    """ % ("Work on payments. " * 30)

    posting = generic.extract(html, "https://www.linkedin.com/jobs/view/1")
    assert posting.company is None
    assert posting.title == "Backend Intern"
