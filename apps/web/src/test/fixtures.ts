import type { Application, AppStatus, Board, BoardColumn } from "../api/types";

/**
 * A complete, boring `Application`. Building the real shape rather than casting a partial
 * one keeps a test honest: if a field is added to the type, this stops compiling instead
 * of quietly handing components an object that lies about what the API returns.
 */
export function makeApplication(overrides: Partial<Application> & { id: string }): Application {
  return {
    source_url: "https://example.com/jobs/1",
    canonical_url: "https://example.com/jobs/1",
    source_host: "example.com",
    ats_vendor: null,

    company: "Acme",
    company_domain: "example.com",
    title: "Software Engineer",
    location: "Remote",
    is_remote: true,
    employment_type: "full_time",
    req_id: null,

    salary_min: null,
    salary_max: null,
    salary_currency: null,
    salary_period: null,

    description: null,
    description_raw: null,
    description_user: null,
    extraction_meta: {},

    status: "applied",
    board_position: 1024,
    saved_at: "2026-08-01T00:00:00Z",
    applied_at: null,
    posted_at: null,
    closed_at: null,
    next_action_at: null,
    priority: 0,

    ingest_status: "ok",
    notes: null,
    archived_at: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",

    tags: [],
    days_since_applied: null,
    days_since_saved: 1,
    staleness: "none",

    ...overrides,
  };
}

export function makeColumn(status: AppStatus, ids: string[]): BoardColumn {
  return {
    status,
    count: ids.length,
    items: ids.map((id) => makeApplication({ id, status, title: `Role ${id}` })),
  };
}

export function makeBoard(columns: Partial<Record<AppStatus, string[]>>): Board {
  return {
    columns: (Object.entries(columns) as [AppStatus, string[]][]).map(([status, ids]) =>
      makeColumn(status, ids),
    ),
  };
}
