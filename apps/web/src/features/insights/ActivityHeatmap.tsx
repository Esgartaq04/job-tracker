import type { Activity } from "../../api/types";

export interface HeatCell {
  date: string;
  count: number;
  level: 0 | 1 | 2 | 3 | 4;
}

/** Fixed thresholds, so a block's colour means the same thing week to week. */
export function levelFor(count: number): HeatCell["level"] {
  if (count <= 0) return 0;
  if (count === 1) return 1;
  if (count === 2) return 2;
  if (count <= 4) return 3;
  return 4;
}

const LEVEL_CLASS = ["bg-block-0", "bg-block-1", "bg-block-2", "bg-block-3", "bg-block-4"];
const LEGEND = ["0", "1", "2", "3–4", "5+"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Lay days out as week columns, Monday on top. The first column is padded before the
 * first day and the last after today, so every column is a full Monday–Sunday week.
 */
export function buildWeeks(days: Activity["days"]): (HeatCell | null)[][] {
  if (days.length === 0) return [];
  // Dates are plain calendar days; reading them as UTC keeps the weekday stable.
  const weekday = (date: string) => (new Date(`${date}T00:00:00Z`).getUTCDay() + 6) % 7;

  const cells: (HeatCell | null)[] = Array(weekday(days[0].date)).fill(null);
  for (const day of days) cells.push({ ...day, level: levelFor(day.count) });
  while (cells.length % 7 !== 0) cells.push(null);

  const weeks: (HeatCell | null)[][] = [];
  for (let start = 0; start < cells.length; start += 7) weeks.push(cells.slice(start, start + 7));
  return weeks;
}

/** A month name over the first week column that contains the 1st of that month. */
function monthLabel(week: (HeatCell | null)[], index: number): string | null {
  const first = week.find((cell) => cell !== null && Number(cell.date.slice(8)) === 1);
  if (first) return MONTHS[Number(first.date.slice(5, 7)) - 1];
  // The opening column gets its month too, unless a 1st falls just after it.
  if (index === 0) {
    const cell = week.find((entry) => entry !== null);
    if (cell && Number(cell.date.slice(8)) <= 21) return MONTHS[Number(cell.date.slice(5, 7)) - 1];
  }
  return null;
}

function formatDay(date: string): string {
  return `${MONTHS[Number(date.slice(5, 7)) - 1]} ${Number(date.slice(8))}`;
}

/** One block per day for the last six months, shaded by applications sent. */
export function ActivityHeatmap({ days }: { days: Activity["days"] }) {
  const weeks = buildWeeks(days);
  const total = days.reduce((sum, day) => sum + day.count, 0);

  return (
    // Capped so the blocks stay block-sized on a wide screen.
    <div className="max-w-2xl">
      <div
        className="grid gap-[3px]"
        style={{ gridTemplateColumns: `repeat(${weeks.length}, minmax(0, 1fr))` }}
        aria-hidden="true"
      >
        {weeks.map((week, index) => (
          <span key={index} className="h-4 truncate text-[10px] leading-4 text-slate-500">
            {monthLabel(week, index)}
          </span>
        ))}
      </div>
      <div
        role="img"
        aria-label={`${total} applications over the last ${weeks.length} weeks`}
        className="grid grid-flow-col gap-[3px]"
        style={{
          gridTemplateColumns: `repeat(${weeks.length}, minmax(0, 1fr))`,
          gridTemplateRows: "repeat(7, auto)",
        }}
      >
        {weeks.flatMap((week, column) =>
          week.map((cell, row) =>
            cell ? (
              <div
                key={cell.date}
                title={`${cell.count} applied · ${formatDay(cell.date)}`}
                className={`aspect-square ${LEVEL_CLASS[cell.level]} shadow-[inset_1px_1px_0_rgb(255_255_255/0.15),inset_-1px_-1px_0_rgb(0_0_0/0.35)]`}
              />
            ) : (
              <div key={`pad-${column}-${row}`} className="aspect-square" />
            ),
          ),
        )}
      </div>
      <div className="mt-2 flex items-center justify-end gap-1 text-[10px] text-slate-500">
        <span className="mr-1">Fewer</span>
        {LEGEND.map((label, level) => (
          <span key={label} className="flex items-center gap-0.5">
            <span className={`inline-block h-3 w-3 ${LEVEL_CLASS[level]}`} />
            <span>{label}</span>
          </span>
        ))}
        <span className="ml-1">More</span>
      </div>
    </div>
  );
}
