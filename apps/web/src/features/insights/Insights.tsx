import { useFunnel, useSources, useVelocity } from "../../api/hooks";
import { STATUS_LABELS } from "../../api/types";

/** Funnel, weekly velocity, time-in-stage and response rate by source (README §7.4). */
export function Insights() {
  const funnel = useFunnel();
  const velocity = useVelocity();
  const sources = useSources();

  if (funnel.isLoading || velocity.isLoading) {
    return <div className="p-6 text-sm text-slate-500">Crunching…</div>;
  }

  const stages = funnel.data?.stages ?? [];
  const widest = Math.max(1, ...stages.map((stage) => stage.reached));
  const weekly = velocity.data?.weekly ?? [];
  const peakWeek = Math.max(1, ...weekly.map((week) => Math.max(week.saved, week.applied)));

  return (
    <div className="grid gap-4 overflow-y-auto p-4 lg:grid-cols-2">
      <Panel title="Funnel" hint={`${funnel.data?.total ?? 0} tracked`}>
        <div className="space-y-2">
          {stages.map((stage) => (
            <div key={stage.status}>
              <div className="flex justify-between text-xs text-slate-400">
                <span>{STATUS_LABELS[stage.status]}</span>
                <span className="tabular-nums">
                  {stage.reached}
                  {stage.conversion_from_applied != null && stage.status !== "applied"
                    ? ` · ${Math.round(stage.conversion_from_applied * 100)}%`
                    : ""}
                </span>
              </div>
              <div className="mt-1 h-2 rounded bg-surface-card">
                <div
                  className="h-2 rounded bg-accent"
                  style={{ width: `${(stage.reached / widest) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <Stat
            label="Response rate"
            value={
              funnel.data?.response_rate != null
                ? `${Math.round(funnel.data.response_rate * 100)}%`
                : "—"
            }
          />
          <Stat
            label="Median days to first reply"
            value={funnel.data?.median_days_to_first_response?.toString() ?? "—"}
          />
        </dl>
      </Panel>

      <Panel title="Applications per week" hint="last 12 weeks">
        <div className="flex h-40 items-stretch gap-1">
          {weekly.map((week) => (
            // h-full so the bars' percentage heights resolve against the 10rem row.
            <div key={week.week_start} className="flex h-full flex-1 flex-col justify-end gap-0.5">
              <div
                className="rounded-t bg-accent"
                style={{ height: `${(week.applied / peakWeek) * 100}%` }}
                title={`${week.applied} applied, week of ${week.week_start}`}
              />
              <div
                className="rounded-t bg-surface-border"
                style={{ height: `${(week.saved / peakWeek) * 100}%` }}
                title={`${week.saved} saved, week of ${week.week_start}`}
              />
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          <span className="text-accent">■</span> applied ·{" "}
          <span className="text-slate-400">■</span> saved · {velocity.data?.stale_count ?? 0}{" "}
          card(s) need a nudge
        </p>
      </Panel>

      <Panel title="Time in stage" hint="median days">
        <ul className="space-y-1.5 text-sm">
          {(velocity.data?.time_in_stage ?? []).map((row) => (
            <li key={row.status} className="flex justify-between text-slate-300">
              <span>{STATUS_LABELS[row.status]}</span>
              <span className="tabular-nums text-slate-400">
                {row.median_days ?? "—"} · {row.open_count} open
              </span>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="Response rate by source" hint="which boards answer">
        <ul className="space-y-1.5 text-sm">
          {(sources.data ?? []).map((row) => (
            <li key={row.ats_vendor} className="flex justify-between text-slate-300">
              <span className="truncate">{row.ats_vendor}</span>
              <span className="tabular-nums text-slate-400">
                {row.responded}/{row.total} · {Math.round(row.response_rate * 100)}%
              </span>
            </li>
          ))}
          {(sources.data ?? []).length === 0 && (
            <li className="text-slate-500">Nothing tracked yet.</li>
          )}
        </ul>
      </Panel>
    </div>
  );
}

function Panel({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-surface-border bg-surface-raised/50 p-4">
      <header className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-slate-200">{title}</h2>
        {hint && <span className="text-xs text-slate-500">{hint}</span>}
      </header>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-lg text-slate-100 tabular-nums">{value}</dd>
    </div>
  );
}
