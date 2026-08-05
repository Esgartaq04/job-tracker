"""URL normalisation and canonicalisation (README §4.2).

Canonical URLs are what the `(user_id, canonical_url)` unique index is built on, so
re-pasting the same posting with a different tracking suffix focuses the existing card
instead of creating a duplicate.
"""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

#: Exact query keys dropped everywhere.
TRACKING_PARAMS = {
    "gh_src",
    "refid",
    "ref",
    "referrer",
    "trk",
    "trackingid",
    "trackingsource",
    "src",
    "source",
    "fbclid",
    "gclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "lever-origin",
    "lever-source",
    "ashby_jid_source",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
}

#: Prefixes dropped everywhere (utm_*, hiring-platform noise).
TRACKING_PREFIXES = ("utm_", "spa_", "_hs")

_HOST_PREFIX = re.compile(r"^(www|m|jobs-www)\.")

#: Hosts that are job boards / ATS vendors — the hostname says nothing about the employer.
NON_EMPLOYER_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "jobs.smartrecruiters.com",
    "careers.smartrecruiters.com",
    "www.linkedin.com",
    "linkedin.com",
    "www.indeed.com",
    "indeed.com",
    "www.glassdoor.com",
    "www.ziprecruiter.com",
    "apply.workable.com",
    "jobs.jobvite.com",
    "www.builtinnyc.com",
    "workday.com",
}


def normalize_url(url: str) -> str:
    """Add a scheme if missing and strip surrounding noise. Raises on unusable input."""
    candidate = (url or "").strip()
    if not candidate:
        raise ValueError("URL is empty")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate):
        candidate = f"https://{candidate}"

    parts = urlsplit(candidate)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parts.scheme}")
    if not parts.netloc:
        raise ValueError("URL has no host")
    return urlunsplit(parts)


def _is_tracking(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PREFIXES)


def canonicalize(url: str) -> str:
    """Deterministic key for deduplication and cache lookups."""
    parts = urlsplit(normalize_url(url))

    host = parts.hostname or ""
    host = host.lower()
    netloc = host
    if parts.port and parts.port not in (80, 443):
        netloc = f"{host}:{parts.port}"

    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")

    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if not _is_tracking(key)
    ]
    query = urlencode(sorted(query_pairs))

    return urlunsplit(("https", netloc, path, query, ""))


def host_of(url: str) -> str | None:
    try:
        return (urlsplit(normalize_url(url)).hostname or "").lower() or None
    except ValueError:
        return None


def registrable_domain(host: str | None) -> str | None:
    """Good-enough eTLD+1 for email matching in v2. Handles the common two-level
    public suffixes without shipping a full PSL."""
    if not host:
        return None
    host = _HOST_PREFIX.sub("", host.lower())
    labels = host.split(".")
    if len(labels) < 2:
        return host
    two_level = {"co.uk", "com.au", "co.in", "com.br", "co.jp", "co.nz", "com.mx"}
    tail = ".".join(labels[-2:])
    if tail in two_level and len(labels) >= 3:
        return ".".join(labels[-3:])
    return tail


def company_domain_for(url: str) -> str | None:
    """Employer domain, or None when the host belongs to a job board / ATS."""
    host = host_of(url)
    if not host:
        return None
    if host in NON_EMPLOYER_HOSTS or "myworkdayjobs.com" in host:
        return None
    domain = registrable_domain(host)
    if domain in {"greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com"}:
        return None
    return domain


def company_guess_from_url(url: str) -> str | None:
    """Last-resort company name so a failed scrape still yields a labelled card
    (README §4.1, mitigation 3)."""
    host = host_of(url) or ""
    parts = [segment for segment in urlsplit(normalize_url(url)).path.split("/") if segment]

    if "greenhouse.io" in host or "lever.co" in host or "ashbyhq.com" in host:
        if parts:
            slug = parts[1] if parts[0] in {"embed", "v1"} and len(parts) > 1 else parts[0]
            return _humanize(slug)
    if "myworkdayjobs.com" in host:
        return _humanize(host.split(".")[0])
    if "smartrecruiters.com" in host and parts:
        return _humanize(parts[0])

    domain = company_domain_for(url)
    if domain:
        return _humanize(domain.split(".")[0])
    return None


def _humanize(slug: str) -> str:
    cleaned = re.sub(r"[-_]+", " ", slug).strip()
    if not cleaned:
        return slug
    return " ".join(word if word.isupper() else word.capitalize() for word in cleaned.split())
