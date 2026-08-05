export const STATUSES = [
  "saved",
  "applied",
  "oa",
  "phone_screen",
  "interview",
  "final",
  "offer",
  "rejected",
  "withdrawn",
  "ghosted",
] as const;

export type AppStatus = (typeof STATUSES)[number];

export const STATUS_LABELS: Record<AppStatus, string> = {
  saved: "Saved",
  applied: "Applied",
  oa: "OA",
  phone_screen: "Phone screen",
  interview: "Interview",
  final: "Final",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  ghosted: "Ghosted",
};

/** Collapsed by default: the largest, least useful columns (README §7.1). */
export const TERMINAL_STATUSES: AppStatus[] = ["rejected", "withdrawn", "ghosted"];

export type IngestStatus = "pending" | "ok" | "partial" | "failed";

export interface Tag {
  id: string;
  name: string;
  color: string | null;
}

export interface StatusEvent {
  id: number;
  from_status: AppStatus | null;
  to_status: AppStatus;
  occurred_at: string;
  source: "manual" | "email" | "system" | "ai";
  confidence: number | null;
  note: string | null;
}

export interface Application {
  id: string;
  source_url: string;
  canonical_url: string;
  source_host: string | null;
  ats_vendor: string | null;

  company: string | null;
  company_domain: string | null;
  title: string | null;
  location: string | null;
  is_remote: boolean | null;
  employment_type: string | null;
  req_id: string | null;

  salary_min: string | null;
  salary_max: string | null;
  salary_currency: string | null;
  salary_period: string | null;

  description: string | null;
  description_raw: string | null;
  description_user: string | null;
  extraction_meta: Record<string, unknown>;

  status: AppStatus;
  board_position: number;
  saved_at: string;
  applied_at: string | null;
  posted_at: string | null;
  closed_at: string | null;
  next_action_at: string | null;
  priority: number;

  ingest_status: IngestStatus;
  notes: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;

  tags: Tag[];
  days_since_applied: number | null;
  days_since_saved: number | null;
  staleness: "none" | "warn" | "dim" | null;
}

export interface ApplicationDetail extends Application {
  events: StatusEvent[];
}

export interface BoardColumn {
  status: AppStatus;
  count: number;
  items: Application[];
}

export interface Board {
  columns: BoardColumn[];
}

export interface FunnelStage {
  status: AppStatus;
  reached: number;
  conversion_from_applied: number | null;
}

export interface Funnel {
  total: number;
  applied: number;
  stages: FunnelStage[];
  response_rate: number | null;
  median_days_to_first_response: number | null;
}

export interface Velocity {
  weekly: { week_start: string; saved: number; applied: number }[];
  time_in_stage: { status: AppStatus; median_days: number | null; open_count: number }[];
  stale_count: number;
}

export interface SourceBreakdown {
  ats_vendor: string;
  total: number;
  responded: number;
  response_rate: number;
}

export interface IngestAccepted {
  application_id: string;
  ingest_status: IngestStatus;
  duplicate: boolean;
}
