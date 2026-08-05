"""Fractional-index maths (README §5.1)."""

import pytest

from src.services.ranking import MIN_GAP, STEP, needs_respacing, position_between


def test_appending_to_an_empty_column():
    assert position_between(None, None) == STEP


def test_dropping_between_neighbours_takes_the_midpoint():
    assert position_between(1024.0, 2048.0) == 1536.0


def test_dropping_above_the_first_card():
    assert position_between(None, 1024.0) == 1024.0 - STEP


def test_dropping_below_the_last_card():
    assert position_between(1024.0, None) == 2048.0


def test_repeated_subdivision_stays_ordered():
    low, high = 1024.0, 2048.0
    previous = None
    for _ in range(40):
        middle = position_between(low, high)
        assert low < middle < high
        assert middle != previous
        previous = middle
        high = middle


def test_respacing_is_flagged_once_precision_degrades():
    assert not needs_respacing(1024.0, 2048.0)
    assert needs_respacing(1024.0, 1024.0 + MIN_GAP / 2)


@pytest.mark.parametrize(
    ("before", "after"),
    [(None, None), (None, 5.0), (5.0, None)],
)
def test_open_ended_drops_never_ask_for_respacing(before, after):
    assert not needs_respacing(before, after)
