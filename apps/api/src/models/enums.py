from enum import StrEnum


class AppStatus(StrEnum):
    """Board columns, in pipeline order. Fixed enum for v1 — see README §11 Q1."""

    saved = "saved"
    applied = "applied"
    oa = "oa"
    phone_screen = "phone_screen"
    interview = "interview"
    final = "final"
    offer = "offer"
    rejected = "rejected"
    withdrawn = "withdrawn"
    ghosted = "ghosted"


#: Column order used by the board endpoint and the UI.
BOARD_ORDER: list[AppStatus] = list(AppStatus)

#: Terminal columns are collapsed by default (README §7.1).
TERMINAL_STATUSES: set[AppStatus] = {
    AppStatus.rejected,
    AppStatus.withdrawn,
    AppStatus.ghosted,
}


class IngestStatus(StrEnum):
    pending = "pending"
    ok = "ok"
    partial = "partial"
    failed = "failed"


class EventSource(StrEnum):
    manual = "manual"
    email = "email"
    system = "system"
    ai = "ai"
