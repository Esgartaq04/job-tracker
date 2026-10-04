"""Pure helpers behind the Insights page."""

from datetime import date, timedelta

from src.models import AppStatus
from src.routers.stats import compute_streaks, flow_path

TODAY = date(2026, 10, 4)


def days_ago(*offsets: int) -> set[date]:
    return {TODAY - timedelta(days=offset) for offset in offsets}


def test_streaks_are_zero_with_no_applications():
    assert compute_streaks(set(), TODAY) == (0, 0)


def test_current_streak_includes_today():
    assert compute_streaks(days_ago(0, 1, 2), TODAY) == (3, 3)


def test_current_streak_survives_until_today_ends():
    assert compute_streaks(days_ago(1, 2), TODAY) == (2, 2)


def test_a_gap_breaks_the_current_streak_but_not_the_longest():
    assert compute_streaks(days_ago(0, 5, 6, 7, 8), TODAY) == (1, 4)


def test_a_missed_yesterday_ends_the_current_streak():
    assert compute_streaks(days_ago(2, 3), TODAY) == (0, 2)


def test_flow_path_skips_applications_never_sent():
    assert flow_path({AppStatus.saved}, AppStatus.saved, applied=False) == []
    assert flow_path({AppStatus.withdrawn}, AppStatus.withdrawn, applied=False) == []


def test_flow_path_waiting_on_a_reply():
    assert flow_path({AppStatus.applied}, AppStatus.applied, applied=True) == [
        "applied",
        "no_reply",
    ]


def test_flow_path_ends_at_an_active_stage():
    seen = {AppStatus.applied, AppStatus.oa}
    assert flow_path(seen, AppStatus.oa, applied=True) == ["applied", "oa"]


def test_flow_path_declined_offer():
    seen = {AppStatus.applied, AppStatus.offer, AppStatus.withdrawn}
    assert flow_path(seen, AppStatus.withdrawn, applied=True) == [
        "applied",
        "offer",
        "withdrawn",
    ]
