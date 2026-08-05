"""Seed a demo board so the UI has something to show before real pastes land.

    python scripts/seed_demo.py --email you@example.com --password ...

Idempotent per email: re-running replaces that user's applications.
"""

import argparse
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from src.core.db import session_scope  # noqa: E402
from src.core.security import hash_password  # noqa: E402
from src.models import Application, AppStatus, IngestStatus, StatusEvent, Tag, User  # noqa: E402
from src.models.util import utcnow  # noqa: E402
from src.services import ranking  # noqa: E402
from src.services.ingestion.normalize import canonicalize, host_of  # noqa: E402
from src.services.transitions import apply_transition, record_initial_event  # noqa: E402

DEMO = [
    ("Stripe", "SWE Intern, Payments", "New York, NY", AppStatus.saved, ["referral"], 2),
    ("Datadog", "Backend Engineering Intern", "Remote (US)", AppStatus.applied, [], 18),
    ("Snowflake", "Data Platform Intern", "San Mateo, CA", AppStatus.applied, [], 6),
    ("Nvidia", "ML Systems Intern", "Santa Clara, CA", AppStatus.oa, ["oa-due"], 9),
    ("Citadel", "SWE Intern", "Chicago, IL", AppStatus.oa, [], 4),
    ("Google", "STEP Intern", "Chicago, IL", AppStatus.interview, ["referral"], 12),
    ("Ramp", "Backend Intern", "New York, NY", AppStatus.phone_screen, [], 7),
    ("Cisco", "SWE Intern", "Chicago, IL", AppStatus.offer, [], 21),
    ("Meta", "Production Engineering Intern", "Menlo Park, CA", AppStatus.rejected, [], 30),
    ("Amazon", "SDE Intern", "Seattle, WA", AppStatus.rejected, [], 26),
    ("Palantir", "Software Engineer Intern", "Denver, CO", AppStatus.ghosted, [], 45),
]

#: The path a card takes to reach each status, so the timeline and funnel look real.
ROUTES = {
    AppStatus.saved: [],
    AppStatus.applied: [AppStatus.applied],
    AppStatus.oa: [AppStatus.applied, AppStatus.oa],
    AppStatus.phone_screen: [AppStatus.applied, AppStatus.phone_screen],
    AppStatus.interview: [AppStatus.applied, AppStatus.oa, AppStatus.interview],
    AppStatus.offer: [AppStatus.applied, AppStatus.oa, AppStatus.interview, AppStatus.offer],
    AppStatus.rejected: [AppStatus.applied, AppStatus.rejected],
    AppStatus.ghosted: [AppStatus.applied, AppStatus.ghosted],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", default="demo-password-123")
    args = parser.parse_args()

    random.seed(7)
    db = session_scope()
    try:
        user = db.scalar(select(User).where(User.email == args.email.lower()))
        if user is None:
            user = User(email=args.email.lower(), password_hash=hash_password(args.password))
            db.add(user)
            db.flush()
        else:
            existing = db.scalars(select(Application).where(Application.user_id == user.id)).all()
            for application in existing:
                db.execute(delete(StatusEvent).where(StatusEvent.application_id == application.id))
                db.delete(application)
            db.flush()

        now = utcnow()
        for company, title, location, status, tag_names, age_days in DEMO:
            slug = company.lower()
            url = f"https://boards.greenhouse.io/{slug}/jobs/{random.randint(1000, 9999)}"
            saved_at = now - timedelta(days=age_days)

            application = Application(
                user_id=user.id,
                source_url=url,
                canonical_url=canonicalize(url),
                source_host=host_of(url),
                ats_vendor="greenhouse",
                company=company,
                title=title,
                location=location,
                is_remote="Remote" in location,
                employment_type="internship",
                description_raw=(
                    f"## About the role\n\n{company} is hiring a {title}. You'll work "
                    "on production systems alongside the platform team.\n\n"
                    "### Requirements\n- Python or Go\n- Distributed systems coursework\n"
                ),
                extraction_meta={"tier": "ats:greenhouse", "confidence": 1.0},
                status=AppStatus.saved,
                board_position=ranking.next_position(db, user.id, AppStatus.saved),
                saved_at=saved_at,
                ingest_status=IngestStatus.ok,
            )
            if tag_names:
                tags = []
                for name in tag_names:
                    tag = db.scalar(
                        select(Tag).where(Tag.user_id == user.id, Tag.name == name)
                    ) or Tag(user_id=user.id, name=name)
                    db.add(tag)
                    tags.append(tag)
                db.flush()
                application.tags = tags

            db.add(application)
            db.flush()
            record_initial_event(db, application)

            # Walk the card through its route, spacing the transitions out in time.
            steps = ROUTES[status]
            for index, step in enumerate(steps, start=1):
                occurred = saved_at + timedelta(days=index * max(age_days // (len(steps) + 1), 1))
                apply_transition(db, application, step, occurred_at=min(occurred, now))
            application.board_position = ranking.next_position(db, user.id, application.status)
            db.flush()

        db.commit()
        print(f"Seeded {len(DEMO)} applications for {user.email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
