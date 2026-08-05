import type { Application } from "../api/types";

export function faviconFor(application: Application): string | null {
  const domain =
    application.company_domain ?? application.source_host ?? hostOf(application.source_url);
  if (!domain) return null;
  return `https://www.google.com/s2/favicons?domain=${domain}&sz=64`;
}

function hostOf(url: string): string | null {
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

/**
 * "days since applied" when the card has been applied to, "days since saved"
 * otherwise — the distinction the two timestamps exist for (README §2).
 */
export function ageLabel(application: Application): string {
  if (application.applied_at != null && application.days_since_applied != null) {
    return application.days_since_applied === 0
      ? "applied today"
      : `${application.days_since_applied}d`;
  }
  const days = application.days_since_saved ?? 0;
  return days === 0 ? "saved today" : `saved ${days}d`;
}

export function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatSalary(application: Application): string | null {
  const { salary_min, salary_max, salary_currency, salary_period } = application;
  if (!salary_min && !salary_max) return null;
  const currency = salary_currency ?? "USD";
  const suffix = salary_period === "hourly" ? "/hr" : salary_period === "monthly" ? "/mo" : "";
  const format = (value: string) => {
    const amount = Number(value);
    return amount >= 1000 ? `${Math.round(amount / 1000)}k` : `${Math.round(amount)}`;
  };
  const symbol = currency === "USD" ? "$" : `${currency} `;
  if (salary_min && salary_max && salary_min !== salary_max) {
    return `${symbol}${format(salary_min)}–${format(salary_max)}${suffix}`;
  }
  return `${symbol}${format((salary_min ?? salary_max) as string)}${suffix}`;
}

export function employmentLabel(value: string | null): string | null {
  if (!value) return null;
  return {
    internship: "Internship",
    full_time: "Full-time",
    co_op: "Co-op",
    contract: "Contract",
  }[value] ?? value;
}

/** Extract URLs from a multi-line paste; falls back to whole lines. */
export function parseUrls(input: string): string[] {
  return input
    .split(/[\s,]+/)
    .map((token) => token.trim())
    .filter((token) => token.length > 3 && /^(https?:\/\/|[\w-]+\.[\w-]{2,})/i.test(token));
}
