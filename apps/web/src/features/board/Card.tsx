import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { useMoveApplication } from "../../api/hooks";
import type { Application } from "../../api/types";
import { STATUSES, STATUS_LABELS } from "../../api/types";
import { ageLabel, faviconFor, formatSalary } from "../../lib/format";
import { useUi } from "../../lib/store";

interface CardProps {
  application: Application;
  overlay?: boolean;
}

/**
 * Card anatomy per README §7.1: favicon, role (2-line clamp), company, location,
 * an age/staleness indicator, up to two tags. Nothing else — density is the point.
 */
export function Card({ application, overlay = false }: CardProps) {
  const openDrawer = useUi((state) => state.openDrawer);
  const notify = useUi((state) => state.notify);
  const move = useMoveApplication();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: application.id,
    data: { status: application.status },
  });

  /**
   * Alt+←/→ moves a focused card between columns. dnd-kit's keyboard sensor handles
   * lifting and reordering; this is the deterministic cross-column equivalent, so
   * every drag has a keyboard path that doesn't depend on pointer geometry
   * (README §7.6). The drawer's status dropdown is the menu equivalent.
   */
  function moveByKeyboard(direction: -1 | 1) {
    const index = STATUSES.indexOf(application.status) + direction;
    if (index < 0 || index >= STATUSES.length) return;
    const toStatus = STATUSES[index];
    move.mutate(
      { id: application.id, toStatus },
      {
        onSuccess: () => notify(`Moved to ${STATUS_LABELS[toStatus]}`),
        onError: () => notify(`Couldn't move to ${STATUS_LABELS[toStatus]}`, "error"),
      },
    );
  }

  const favicon = faviconFor(application);
  const salary = formatSalary(application);
  const pending = application.ingest_status === "pending";
  const failed = application.ingest_status === "failed";
  const stale = application.staleness;

  return (
    <article
      ref={overlay ? undefined : setNodeRef}
      style={
        overlay ? undefined : { transform: CSS.Translate.toString(transform), transition }
      }
      {...(overlay ? {} : attributes)}
      {...(overlay ? {} : listeners)}
      onClick={() => !isDragging && openDrawer(application.id)}
      onKeyDown={(event) => {
        if (event.key === "Enter") openDrawer(application.id);
        if (event.altKey && (event.key === "ArrowRight" || event.key === "ArrowLeft")) {
          event.preventDefault();
          moveByKeyboard(event.key === "ArrowRight" ? 1 : -1);
        }
      }}
      aria-label={`${application.title ?? "Untitled"} at ${application.company ?? "unknown company"}, ${STATUS_LABELS[application.status]}. Alt+arrow keys move it between columns.`}
      className={[
        "group cursor-pointer rounded-lg border bg-surface-card px-3 py-2.5 text-left shadow-sm",
        "transition hover:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent",
        overlay ? "rotate-1 shadow-2xl ring-2 ring-accent" : "",
        isDragging ? "opacity-40" : "",
        stale === "dim" ? "border-surface-border opacity-60" : "border-surface-border",
        failed ? "border-stale-warn/70" : "",
      ].join(" ")}
    >
      <div className="flex items-start gap-2">
        {favicon ? (
          <img
            src={favicon}
            alt=""
            width={16}
            height={16}
            className="mt-0.5 h-4 w-4 shrink-0 rounded-sm"
            loading="lazy"
          />
        ) : (
          <span className="mt-0.5 h-4 w-4 shrink-0 rounded-sm bg-surface-border" />
        )}
        <div className="min-w-0 flex-1">
          <h3 className="line-clamp-2 text-sm font-medium leading-snug text-slate-100">
            {pending && application.title === "Untitled" ? (
              <span className="inline-block h-3.5 w-32 animate-pulse rounded bg-surface-border" />
            ) : (
              application.title ?? "Untitled"
            )}
          </h3>
          <p className="mt-0.5 truncate text-xs text-slate-400">
            {application.company ?? "Unknown company"}
          </p>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-slate-400">
        {application.location && (
          <span className="truncate" title={application.location}>
            ⚲ {application.is_remote ? "Remote" : application.location}
          </span>
        )}
        <span
          className={
            stale === "warn"
              ? "text-stale-warn"
              : stale === "dim"
                ? "text-stale-dim"
                : "text-slate-400"
          }
          title={
            stale === "warn"
              ? "No movement in 14+ days"
              : stale === "dim"
                ? "No movement in 30+ days"
                : undefined
          }
        >
          ⏱ {ageLabel(application)}
          {stale === "warn" ? " ⚠" : ""}
        </span>
        {salary && <span className="text-emerald-300/80">{salary}</span>}
      </div>

      {(application.tags.length > 0 || failed) && (
        <div className="mt-2 flex flex-wrap gap-1">
          {failed && (
            <span className="rounded bg-stale-warn/20 px-1.5 py-0.5 text-[10px] text-stale-warn">
              couldn&apos;t read posting — add details
            </span>
          )}
          {application.tags.slice(0, 2).map((tag) => (
            <span
              key={tag.id}
              className="rounded bg-surface-border/70 px-1.5 py-0.5 text-[10px] text-slate-300"
            >
              #{tag.name}
            </span>
          ))}
        </div>
      )}
    </article>
  );
}
