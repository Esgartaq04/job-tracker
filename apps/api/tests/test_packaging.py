"""The deployed image has to carry what the deployed code imports.

Tier 4 was dead in the container for exactly this reason: `anthropic` sits behind an
optional extra, the Dockerfile installed the bare package, and `tiers/llm.py` logs and
returns None on ImportError rather than raising — so the pipeline silently stopped at
Tier 2 even with a key configured. Nothing failed; it just quietly got worse.
"""

import re
import tomllib
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]

INSTALL_LINE = re.compile(r"pip install\s+[\"']?\.(?:\[(?P<extras>[^\]]*)\])?[\"']?")


def dockerfile_extras() -> set[str]:
    match = INSTALL_LINE.search((API_ROOT / "Dockerfile").read_text())
    assert match, "Dockerfile no longer installs the project — this test needs updating"
    return {extra.strip() for extra in (match.group("extras") or "").split(",") if extra.strip()}


def declared_extras() -> dict[str, list[str]]:
    pyproject = tomllib.loads((API_ROOT / "pyproject.toml").read_text())
    return pyproject["project"]["optional-dependencies"]


def test_the_image_installs_only_extras_that_exist():
    """A typo in the extra name is silent: pip installs the package and skips it."""
    unknown = dockerfile_extras() - declared_extras().keys()
    assert not unknown, f"Dockerfile installs extras that pyproject doesn't define: {unknown}"


def test_the_image_carries_the_llm_extra():
    """Without it, ANTHROPIC_API_KEY is set and Tier 4 still never runs."""
    assert "llm" in dockerfile_extras(), (
        "apps/api/Dockerfile must install '.[llm]' or Tier 4 is dead in the container "
        "even with a key configured — see docs/DEPLOYMENT.md §3.2"
    )


def test_the_image_does_not_carry_the_browser_extra():
    """Playwright's download is hundreds of megabytes and will not fit the 512 MB
    instance the API is deployed on. Tier 3 gets its own image or it doesn't ship."""
    assert "browser" not in dockerfile_extras()


def test_tier_4_degrades_instead_of_crashing_when_the_extra_is_missing(monkeypatch):
    """The safety net under the test above: a missing `anthropic` must cost the tier,
    not the request."""
    import builtins

    from src.services.ingestion.tiers import llm

    real_import = builtins.__import__

    def refuse_anthropic(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_anthropic)
    monkeypatch.setattr(llm.settings, "anthropic_api_key", "sk-test", raising=False)

    assert llm.extract("a job posting. " * 100, url="https://example.com/jobs/1") is None
