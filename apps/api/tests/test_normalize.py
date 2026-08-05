"""URL canonicalisation — the key the duplicate index is built on (README §4.2)."""

import pytest

from src.services.ingestion.normalize import (
    canonicalize,
    company_domain_for,
    company_guess_from_url,
    normalize_url,
)


def test_tracking_params_are_stripped():
    assert (
        canonicalize("https://boards.greenhouse.io/stripe/jobs/123?gh_src=abc&utm_source=linkedin")
        == "https://boards.greenhouse.io/stripe/jobs/123"
    )


def test_the_same_posting_pasted_two_ways_is_one_key():
    a = canonicalize("http://WWW.example.com/careers/job/42/?utm_campaign=x#apply")
    b = canonicalize("https://www.example.com/careers/job/42")
    assert a == b


def test_meaningful_query_params_survive_and_sort():
    assert canonicalize("https://example.com/jobs?b=2&a=1") == "https://example.com/jobs?a=1&b=2"


def test_a_bare_host_gets_a_scheme():
    assert normalize_url("example.com/jobs/1").startswith("https://")


@pytest.mark.parametrize("bad", ["", "   ", "ftp://example.com/x", "https://"])
def test_unusable_urls_are_rejected(bad):
    with pytest.raises(ValueError):
        normalize_url(bad)


def test_job_boards_are_not_treated_as_employer_domains():
    assert company_domain_for("https://boards.greenhouse.io/stripe/jobs/1") is None
    assert company_domain_for("https://careers.datadoghq.com/detail/1") == "datadoghq.com"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://boards.greenhouse.io/stripe/jobs/1", "Stripe"),
        ("https://jobs.lever.co/ramp-labs/uuid", "Ramp Labs"),
        ("https://nvidia.wd5.myworkdayjobs.com/en-US/x/job/y", "Nvidia"),
        ("https://careers.datadoghq.com/detail/1", "Datadoghq"),
    ],
)
def test_company_is_guessed_from_the_url_when_scraping_fails(url, expected):
    assert company_guess_from_url(url) == expected
