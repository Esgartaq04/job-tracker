import { sankey, sankeyLeft, sankeyLinkHorizontal, type SankeyLink, type SankeyNode } from "d3-sankey";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Flow, FlowNode } from "../../api/types";

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

/** Where applications went after being sent, from Applied to each outcome. */
export function Sankey({ flow }: { flow: Flow }) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(MIN_WIDTH);
  const [hovered, setHovered] = useState<string | null>(null);

  useEffect(() => {
    const element = container.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(MIN_WIDTH, Math.floor(entry.contentRect.width))),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

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

  return (
    <div>
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
              const dimmed = hovered !== null && hovered !== key;
              return (
                <path
                  key={key}
                  d={path(link) ?? undefined}
                  className={KIND[target.id].stroke}
                  strokeWidth={Math.max(2, link.width ?? 0)}
                  strokeOpacity={dimmed ? 0.12 : hovered === key ? 0.7 : 0.38}
                  onMouseEnter={() => setHovered(key)}
                  onMouseLeave={() => setHovered(null)}
                >
                  <title>{`${source.label} → ${target.label}: ${link.value}`}</title>
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
            return (
              <g key={node.id}>
                <rect
                  x={x0}
                  y={y0}
                  width={x1 - x0}
                  height={Math.max(2, y1 - y0)}
                  className={`${KIND[node.id].fill} stroke-black/70`}
                  strokeWidth={1.5}
                >
                  <title>{`${node.label}: ${node.value}`}</title>
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
