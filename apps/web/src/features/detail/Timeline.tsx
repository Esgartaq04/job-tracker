import type { StatusEvent } from "../../api/types";
import { STATUS_LABELS } from "../../api/types";
import { formatDateTime } from "../../lib/format";

const SOURCE_LABELS: Record<StatusEvent["source"], string> = {
  manual: "you",
  email: "email",
  system: "system",
  ai: "AI",
};

export function Timeline({ events }: { events: StatusEvent[] }) {
  if (events.length === 0) {
    return <p className="text-sm text-slate-500">No transitions recorded yet.</p>;
  }

  return (
    <ol className="relative ml-2 border-l border-surface-border pl-4">
      {events.map((event, index) => {
        const previous = events[index - 1];
        const gapDays = previous
          ? Math.round(
              (new Date(event.occurred_at).getTime() -
                new Date(previous.occurred_at).getTime()) /
                86_400_000,
            )
          : null;

        return (
          <li key={event.id} className="relative pb-4 last:pb-0">
            <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-accent" />
            <p className="text-sm text-slate-200">
              {event.from_status
                ? `${STATUS_LABELS[event.from_status]} → ${STATUS_LABELS[event.to_status]}`
                : `Tracked as ${STATUS_LABELS[event.to_status]}`}
            </p>
            <p className="mt-0.5 text-xs text-slate-500">
              {formatDateTime(event.occurred_at)} · {SOURCE_LABELS[event.source]}
              {gapDays !== null && gapDays > 0 ? ` · ${gapDays}d in previous stage` : ""}
            </p>
            {event.note && <p className="mt-1 text-xs text-slate-400">{event.note}</p>}
          </li>
        );
      })}
    </ol>
  );
}
