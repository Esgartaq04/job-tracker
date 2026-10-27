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


def test_anthropic_is_a_core_dependency():
    """Every user brings their own Claude key, so the SDK can't sit behind an extra the
    image might not install."""
    pyproject = tomllib.loads((API_ROOT / "pyproject.toml").read_text())
    deps = pyproject["project"]["dependencies"]
    assert any(d.startswith("anthropic") for d in deps)
    assert "llm" not in declared_extras()


def test_the_image_does_not_carry_the_browser_extra():
    """Playwright's download is hundreds of megabytes and will not fit the 512 MB
    instance the API is deployed on. Tier 3 gets its own image or it doesn't ship."""
    assert "browser" not in dockerfile_extras()


def test_tier_4_degrades_instead_of_crashing_when_anthropic_is_missing(
    monkeypatch, db_session, user
):
    """The safety net under the test above: a missing `anthropic` must cost the tier,
    not the request, even for a user with a key saved."""
    import builtins

    from src.services import ai, ai_keys
    from src.services.ingestion.tiers import llm

    ai_keys.save_key(db_session, user.id, "sk-ant-api03-" + "p" * 40)
    db_session.commit()

    real_import = builtins.__import__

    def refuse_anthropic(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_anthropic)

    client = ai.client_or_none(db_session, user.id)
    assert client is None
    text = "a job posting. " * 100
    assert llm.extract(text, url="https://example.com/jobs/1", client=client) is None
