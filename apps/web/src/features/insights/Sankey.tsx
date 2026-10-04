import { sankey, sankeyLeft, sankeyLinkHorizontal, type SankeyLink, type SankeyNode } from "d3-sankey";
import { useEffect, useMemo, useRef, useState } from "react";

import { STATUS_LABELS, type Flow, type FlowApplication, type FlowNode } from "../../api/types";
import { useUi } from "../../lib/store";

type Node = FlowNode;
type Link = Flow["links"][number];
type LaidNode = SankeyNode<Node, Link>;
type LaidLink = SankeyLink<Node, Link>;

/** Colour carries what kind of step it is; the label on every node carries which one. */
const KIND: Record<FlowNode["id"], { fill: string; stroke: string }> = {
  applied: { fill: "fill-chart-stage", stroke: "stroke-chart-stage" },
  oa: { fill: "fill-chart-stage", stroke: "stroke-chart-stage" },
  phone_screen: { fill: "fill-chart-stage", stroke: "stroke-chart-stage" },
  interview: { fill: "fill-chart-stage", stroke: "stroke-chart-stage" },
  final: { fill: "fill-chart-stage", stroke: "stroke-chart-stage" },
  offer: { fill: "fill-chart-offer", stroke: "stroke-chart-offer" },
  rejected: { fill: "fill-chart-reject", stroke: "stroke-chart-reject" },
  ghosted: { fill: "fill-chart-neutral", stroke: "stroke-chart-neutral" },
  withdrawn: { fill: "fill-chart-neutral", stroke: "stroke-chart-neutral" },
  no_reply: { fill: "fill-chart-neutral", stroke: "stroke-chart-neutral" },
  // Never sent as a node (the flow starts at Applied); here to satisfy the type.
  saved: { fill: "fill-chart-neutral", stroke: "stroke-chart-neutral" },
};

const HEIGHT = 340;
// Below this the labels collide, so the chart scrolls sideways instead of squeezing.
const MIN_WIDTH = 620;
// Matches the popover's w-72, so it can be kept inside the panel.
const POPOVER_WIDTH = 288;

/** What a click on a branch or node opened: which listings, and where to show them. */
interface Selection {
  key: string;
  title: string;
  ids: string[];
  x: number;
  y: number;
  trigger: SVGElement;
}

const nodeKey = (id: string) => `node:${id}`;

/** Where applications went after being sent, from Applied to each outcome. */
export function Sankey({ flow }: { flow: Flow }) {
  const container = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(MIN_WIDTH);
  const [hovered, setHovered] = useState<string | null>(null);
  const [selected, setSelected] = useState<Selection | null>(null);

  useEffect(() => {
    const element = container.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(MIN_WIDTH, Math.floor(entry.contentRect.width))),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // A refetch can drop the listings a popover was showing; start over rather than
  // point at a branch that may no longer exist.
  useEffect(() => setSelected(null), [flow]);

  const graph = useMemo(() => {
    if (flow.links.length === 0) return null;
    return (
      sankey<Node, Link>()
        .nodeId((node) => node.id)
        .nodeAlign(sankeyLeft)
        // Keep the API's order: pipeline stages on top, outcomes beneath.
        .nodeSort(null)
        .nodeWidth(14)
        .nodePadding(18)
        .extent([
          [1, 8],
          [width - 1, HEIGHT - 8],
        ])({
        // The layout mutates its input; hand it copies so the query cache stays clean.
        nodes: flow.nodes.map((node) => ({ ...node })),
        links: flow.links.map((link) => ({ ...link })),
      })
    );
  }, [flow, width]);

  const byId = useMemo(
    () => new Map(flow.applications.map((application) => [application.id, application])),
    [flow],
  );

  if (!graph) {
    return (
      <p className="py-10 text-center text-sm text-slate-500">
        Nothing sent yet. Move a card to Applied and the flow starts here.
      </p>
    );
  }

  const path = sankeyLinkHorizontal<Node, Link>();
  const linkKey = (link: LaidLink) =>
    `${(link.source as LaidNode).id}->${(link.target as LaidNode).id}`;

  /** Open (or, on a second click, close) the listings for a branch or node. */
  function toggle(
    key: string,
    title: string,
    ids: string[],
    trigger: SVGElement,
    point?: { clientX: number; clientY: number },
  ) {
    if (selected?.key === key) {
      setSelected(null);
      return;
    }
    const bounds = frame.current?.getBoundingClientRect();
    // Keyboard has no pointer, so anchor on the middle of what was focused.
    const box = trigger.getBoundingClientRect();
    const clientX = point?.clientX ?? box.left + box.width / 2;
    const clientY = point?.clientY ?? box.top + box.height / 2;
    const frameWidth = bounds?.width ?? width;
    setSelected({
      key,
      title,
      ids,
      x: Math.max(0, Math.min(clientX - (bounds?.left ?? 0), frameWidth - POPOVER_WIDTH)),
      y: clientY - (bounds?.top ?? 0) + 10,
      trigger,
    });
  }

  function onKey(event: React.KeyboardEvent<SVGElement>, open: () => void) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  }

  const active = hovered ?? selected?.key ?? null;
  const touches = (link: LaidLink, key: string) =>
    key === nodeKey((link.source as LaidNode).id) || key === nodeKey((link.target as LaidNode).id);

  return (
    <div ref={frame} className="relative">
      <div ref={container} className="overflow-x-auto">
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={`Flow of ${flow.total_applied} applications from Applied to their outcomes`}
          className="block"
        >
          <g fill="none">
            {graph.links.map((link) => {
              const key = linkKey(link);
              const source = link.source as LaidNode;
              const target = link.target as LaidNode;
              const lit = active === key || (active !== null && touches(link, active));
              const dimmed = active !== null && !lit;
              const title = `${source.label} → ${target.label}`;
              const open = (point?: { clientX: number; clientY: number }, element?: SVGElement) =>
                element && toggle(key, title, link.application_ids, element, point);
              return (
                <path
                  key={key}
                  data-flow-key={key}
                  d={path(link) ?? undefined}
                  className={`${KIND[target.id].stroke} cursor-pointer outline-none`}
                  strokeWidth={Math.max(2, link.width ?? 0)}
                  strokeOpacity={dimmed ? 0.12 : lit ? 0.7 : 0.38}
                  tabIndex={0}
                  role="button"
                  aria-label={`${title}: ${link.value} ${link.value === 1 ? "application" : "applications"}`}
                  aria-expanded={selected?.key === key}
                  onMouseEnter={() => setHovered(key)}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => setHovered(key)}
                  onBlur={() => setHovered(null)}
                  onClick={(event) => open(event, event.currentTarget)}
                  onKeyDown={(event) => onKey(event, () => open(undefined, event.currentTarget))}
                >
                  <title>{`${title}: ${link.value} — click to list them`}</title>
                </path>
              );
            })}
          </g>
          {graph.nodes.map((node) => {
            const x0 = node.x0 ?? 0;
            const x1 = node.x1 ?? 0;
            const y0 = node.y0 ?? 0;
            const y1 = node.y1 ?? 0;
            // Labels sit to the right of a node, except in the last column where
            // there's no room left.
            const right = x1 < width - 2;
            const key = nodeKey(node.id);
            // Applied has nothing flowing in, so it's everything flowing out.
            const edges = (node.targetLinks ?? []).length ? node.targetLinks : node.sourceLinks;
            const ids = [...new Set((edges ?? []).flatMap((link) => link.application_ids))];
            const open = (point?: { clientX: number; clientY: number }, element?: SVGElement) =>
              element && toggle(key, node.label, ids, element, point);
            return (
              <g key={node.id}>
                <rect
                  data-flow-key={key}
                  x={x0}
                  y={y0}
                  width={x1 - x0}
                  height={Math.max(2, y1 - y0)}
                  className={`${KIND[node.id].fill} cursor-pointer outline-none ${
                    active === key ? "stroke-slate-100" : "stroke-black/70"
                  }`}
                  strokeWidth={1.5}
                  tabIndex={0}
                  role="button"
                  aria-label={`${node.label}: ${node.value} ${node.value === 1 ? "application" : "applications"}`}
                  aria-expanded={selected?.key === key}
                  onMouseEnter={() => setHovered(key)}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => setHovered(key)}
                  onBlur={() => setHovered(null)}
                  onClick={(event) => open(event, event.currentTarget)}
                  onKeyDown={(event) => onKey(event, () => open(undefined, event.currentTarget))}
                >
                  <title>{`${node.label}: ${node.value} — click to list them`}</title>
                </rect>
                <text
                  x={right ? x1 + 6 : x0 - 6}
                  y={(y0 + y1) / 2}
                  dy="0.35em"
                  textAnchor={right ? "start" : "end"}
                  className="pointer-events-none fill-slate-100 text-xs [paint-order:stroke] [stroke-linejoin:round] [stroke-width:3px] [stroke:rgb(var(--surface-raised))]"
                >
                  {node.label}
                  <tspan className="fill-slate-400"> {node.value}</tspan>
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {selected && (
        <FlowPopover
          selection={selected}
          applications={selected.ids.flatMap((id) => byId.get(id) ?? [])}
          onClose={(refocus) => {
            if (refocus && selected.trigger.isConnected) selected.trigger.focus();
            setSelected(null);
          }}
        />
      )}

      <details className="mt-2 text-xs text-slate-400">
        <summary className="cursor-pointer select-none hover:text-slate-200">Show as table</summary>
        <table className="mt-2 w-full max-w-md text-left">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1 font-normal">From</th>
              <th className="py-1 font-normal">To</th>
              <th className="py-1 text-right font-normal">Applications</th>
            </tr>
          </thead>
          <tbody className="text-slate-300">
            {graph.links.map((link) => (
              <tr key={linkKey(link)}>
                <td className="py-0.5">{(link.source as LaidNode).label}</td>
                <td className="py-0.5">{(link.target as LaidNode).label}</td>
                <td className="py-0.5 text-right tabular-nums">{link.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

/** The listings behind one branch or node, floating where it was clicked. */
function FlowPopover({
  selection,
  applications,
  onClose,
}: {
  selection: Selection;
  applications: FlowApplication[];
  /** `refocus` is false when the user clicked elsewhere and focus should stay there. */
  onClose: (refocus: boolean) => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const openDrawer = useUi((state) => state.openDrawer);

  useEffect(() => {
    panel.current?.querySelector<HTMLElement>("[data-listing]")?.focus();
  }, [selection.key]);

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Element;
      if (panel.current?.contains(target)) return;
      // Clicks on the chart's own branches toggle or switch the popover themselves.
      if (target.closest?.("[data-flow-key]")) return;
      onClose(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose(true);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  const count = applications.length;

  return (
    <div
      ref={panel}
      role="dialog"
      aria-label={`${selection.title}: ${count} ${count === 1 ? "listing" : "listings"}`}
      className="mc-panel absolute z-30 w-72 animate-fade-in bg-surface-raised shadow-xl"
      style={{ left: selection.x, top: selection.y }}
    >
      <header className="flex items-baseline justify-between gap-2 border-b-2 border-black/60 px-3 py-2">
        <h3 className="mc-shadow text-sm text-slate-100">
          {selection.title}
          <span className="ml-1.5 text-xs text-slate-400">
            {count} {count === 1 ? "listing" : "listings"}
          </span>
        </h3>
        <button
          type="button"
          aria-label="Close listings"
          onClick={() => onClose(true)}
          className="px-1 text-sm text-slate-400 hover:text-slate-100"
        >
          ✕
        </button>
      </header>
      <ul className="max-h-64 overflow-y-auto py-1">
        {applications.map((application) => (
          <li key={application.id}>
            <button
              type="button"
              data-listing
              onClick={() => {
                // Hand focus back to the branch first, so closing the drawer returns there.
                onClose(true);
                openDrawer(application.id);
              }}
              className="block w-full px-3 py-1.5 text-left text-sm hover:bg-surface-border/60 focus:bg-surface-border/60 focus:outline-none"
            >
              <span className="block truncate text-slate-100">
                {application.company ?? "Unknown company"}
              </span>
              <span className="flex justify-between gap-2 text-xs text-slate-400">
                <span className="truncate">{application.title ?? "Untitled role"}</span>
                <span className="shrink-0 text-slate-500">{STATUS_LABELS[application.status]}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
