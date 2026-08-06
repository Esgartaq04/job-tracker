import { useEffect, useRef, useState } from "react";

import { useReminders } from "../../api/hooks";
import type { Reminder } from "../../api/types";
import { useUi } from "../../lib/store";

const KIND_TONE: Record<Reminder["kind"], string> = {
  overdue: "text-stale-warn",
  due_today: "text-stale-warn",
  upcoming: "text-slate-300",
  stale: "text-stale-dim",
};

/**
 * The passive half of the product: staleness and due dates are worth nothing if you
 * have to go looking for them, so what needs a nudge sits above the board (README §7.1
 * — "the single highest-value passive feature").
 */
export function NeedsAttention() {
  const [expanded, setExpanded] = useState(false);
  const openDrawer = useUi((state) => state.openDrawer);
  const { data } = useReminders();

  useDesktopNotifications(data?.summary, data?.count ?? 0);

  if (!data || data.count === 0) return null;

  const urgent = data.items.filter(
    (item) => item.kind === "overdue" || item.kind === "due_today",
  );

  return (
    <section
      aria-label="Needs attention"
      className="border-b border-surface-border bg-surface-raised/40 px-4 py-2"
    >
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 text-left text-sm"
      >
        <span className={urgent.length > 0 ? "text-stale-warn" : "text-slate-400"}>
          {urgent.length > 0 ? "⚠" : "⏱"}
        </span>
        <span className="text-slate-200">{data.summary}</span>
        <span className="ml-auto text-xs text-slate-500">
          {expanded ? "hide" : `show ${data.count}`}
        </span>
      </button>

      {expanded && (
        <ul className="mt-2 space-y-1">
          {data.items.map((item) => (
            <li key={item.application.id}>
              <button
                type="button"
                onClick={() => openDrawer(item.application.id)}
                className="flex w-full items-baseline gap-2 rounded px-1 py-1 text-left text-sm hover:bg-surface-card/60"
              >
                <span className="truncate text-slate-200">
                  {item.application.company ?? "Unknown"}
                </span>
                <span className="truncate text-xs text-slate-500">
                  {item.application.title}
                </span>
                <span className={`ml-auto shrink-0 text-xs ${KIND_TONE[item.kind]}`}>
                  {item.reason}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Desktop notifications, asked for only once the user has something to be notified
 * about — a permission prompt on first load, before the board has any cards, gets
 * denied and then can't be asked again.
 */
function useDesktopNotifications(summary: string | undefined, count: number) {
  const lastNotified = useRef<string | null>(null);

  useEffect(() => {
    if (!summary || count === 0) return;
    if (!("Notification" in window)) return;

    // Only once per distinct summary per session: the same "2 overdue" every poll is
    // nagging, a change is news.
    if (lastNotified.current === summary) return;

    if (Notification.permission === "granted") {
      lastNotified.current = summary;
      new Notification("Job tracker", { body: summary, tag: "job-tracker-reminders" });
    }
  }, [summary, count]);
}

/** Called from the account menu, where asking is an explicit user action. */
export async function enableDesktopNotifications(): Promise<NotificationPermission> {
  if (!("Notification" in window)) return "denied";
  if (Notification.permission !== "default") return Notification.permission;
  return Notification.requestPermission();
}
