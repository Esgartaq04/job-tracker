import { useActivity, useFlow, useFunnel, useVelocity } from "../../api/hooks";
import { ActivityHeatmap } from "./ActivityHeatmap";
import { Sankey } from "./Sankey";
import { XpBar } from "./XpBar";

/** Total sent, where they went (Sankey), the weekly goal, and daily activity. */
export function Insights() {
  const funnel = useFunnel();
  const flow = useFlow();
  const velocity = useVelocity();
  const activity = useActivity();

  if (funnel.isLoading || flow.isLoading || activity.isLoading) {
    return <div className="p-6 text-sm text-slate-500">Loading chunks…</div>;
  }

  const weekly = velocity.data?.weekly ?? [];
  const peakWeek = Math.max(1, ...weekly.map((week) => Math.max(week.saved, week.applied)));
  const streak = activity.data?.current_streak ?? 0;
  const best = activity.data?.longest_streak ?? 0;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto grid max-w-6xl gap-4 p-4 lg:grid-cols-3">
        <dl className="grid grid-cols-2 gap-3 lg:col-span-3 lg:grid-cols-4">
          <Stat
            label="Total applied"
            value={(flow.data?.total_applied ?? 0).toString()}
            hint={`${funnel.data?.total ?? 0} tracked in all`}
            hero
          />
          <Stat
            label="Response rate"
            value={
              funnel.data?.response_rate != null
                ? `${Math.round(funnel.data.response_rate * 100)}%`
                : "—"
            }
            hint="heard back at all"
          />
          <Stat
            label="Days to first reply"
            value={funnel.data?.median_days_to_first_response?.toString() ?? "—"}
            hint="median"
          />
          <Stat
            label="Daily streak"
            value={`${streak} ${streak === 1 ? "day" : "days"}`}
            hint={`best ${best}`}
          />
        </dl>

        <Panel title="Where your applications went" hint="from Applied to outcome" wide>
          {flow.data && <Sankey flow={flow.data} />}
        </Panel>

        <Panel title="Weekly goal" hint="resets Monday">
          <XpBar thisWeek={activity.data?.this_week ?? 0} />
        </Panel>

        <Panel title="Applications per week" hint="last 12 weeks" className="lg:col-span-2">
          <div className="flex h-40 items-stretch gap-1">
            {weekly.map((week) => (
              // h-full so the bars' percentage heights resolve against the 10rem row.
              <div key={week.week_start} className="flex h-full flex-1 flex-col justify-end gap-0.5">
                <div
                  className="bg-chart-stage"
                  style={{ height: `${(week.applied / peakWeek) * 100}%` }}
                  title={`${week.applied} applied, week of ${week.week_start}`}
                />
                <div
                  className="bg-chart-neutral/60"
                  style={{ height: `${(week.saved / peakWeek) * 100}%` }}
                  title={`${week.saved} saved, week of ${week.week_start}`}
                />
              </div>
            ))}
          </div>
          <p className="mt-2 flex flex-wrap items-center gap-x-3 text-xs text-slate-500">
            <span className="flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 bg-chart-stage" /> applied
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 bg-chart-neutral/60" /> saved
            </span>
            <span>· {velocity.data?.stale_count ?? 0} card(s) need a nudge</span>
          </p>
        </Panel>

        <Panel title="Activity" hint="applications per day, last 6 months" wide>
          <ActivityHeatmap days={activity.data?.days ?? []} />
        </Panel>
      </div>
    </div>
  );
}

function Panel({
  title,
  hint,
  wide,
  className = "",
  children,
}: {
  title: string;
  hint?: string;
  wide?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`mc-panel min-w-0 p-4 ${wide ? "lg:col-span-3" : ""} ${className}`}>
      <header className="mb-3 flex items-baseline justify-between gap-2">
        <h2 className="mc-shadow text-sm font-bold text-slate-100">{title}</h2>
        {hint && <span className="text-right text-xs text-slate-500">{hint}</span>}
      </header>
      {children}
    </section>
  );
}

function Stat({
  label,
  value,
  hint,
  hero,
}: {
  label: string;
  value: string;
  hint?: string;
  hero?: boolean;
}) {
  return (
    <div className={`mc-panel p-3 ${hero ? "border-accent-ink/70" : ""}`}>
      <dt className="text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd
        className={`mc-shadow mt-1 font-[family-name:var(--font-numeric)] tabular-nums text-slate-100 ${hero ? "text-4xl" : "text-2xl"}`}
      >
        {value}
      </dd>
      {hint && <dd className="text-xs text-slate-500">{hint}</dd>}
    </div>
  );
}
