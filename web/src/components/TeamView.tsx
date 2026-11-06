import { motion } from "framer-motion";
import { GitBranch, Network } from "lucide-react";
import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";

import { agentUi, formatDuration, isWorking, swimlane, type Lane, type LaneNode, type RunView, type UiStatus } from "../model";
import { roleLabel, SPECIALISTS } from "../roles";
import { agentToken, MOTION, STATUS } from "../theme/tokens";
import { AgentAvatar } from "../ui/AgentAvatar";
import { cx, useReducedMotion } from "../ui/bits";
import { StatusChip, StatusIcon } from "../ui/StatusChip";

// ------------------------------------------------------------------------------------------------ swimlane

/** A stage's colour on the rail: the most urgent state of the specialists in it. */
function laneStatus(lane: Lane): UiStatus {
  const order: UiStatus[] = ["escalated", "failed", "running", "blocked", "queued", "passed", "idle"];
  return order.find((s) => lane.nodes.some((n) => n.ui === s)) ?? "idle";
}

function NodeCard({ node, onOpen }: { node: LaneNode; onOpen: (role: string) => void }) {
  const label = roleLabel(node.role);
  const t = node.task;
  const seconds = t && t.endTs ? t.endTs - t.startTs : null;
  return (
    <button
      type="button" onClick={() => onOpen(node.role)} aria-label={`${label}: ${STATUS[node.ui].label}${node.tries ? `, try ${node.tries}` : ""}${node.blockedBy ? `, waiting on ${roleLabel(node.blockedBy)}` : ""}. Open details.`}
      className={cx("raised flex w-full min-w-0 items-center gap-3 p-3 text-left transition-colors hover:bg-overlay", node.ui === "running" && "border-running/50", (node.ui === "escalated" || node.ui === "failed") && STATUS[node.ui].ring)}
    >
      <AgentAvatar role={node.role} live={node.ui === "running"} />
      <span className="min-w-0 flex-1">
        <span className="block truncate font-semibold">{label}</span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
          <StatusChip status={node.ui} size="sm" />
          {node.tries > 0 && <span className="text-[13px] text-fg-3">Try {node.tries}{seconds !== null ? ` · ${formatDuration(seconds)}` : ""}</span>}
        </span>
        {node.blockedBy && <span className="mt-1 block text-[13px] text-blocked">Waiting on {roleLabel(node.blockedBy)}</span>}
      </span>
    </button>
  );
}

function Swimlane({ view, onOpen }: { view: RunView; onOpen: (role: string) => void }) {
  const lanes = swimlane(view);
  if (!lanes.length) return <p className="py-8 text-center text-fg-3">No specialist has been given work yet. Stages appear here in the order they run.</p>;
  return (
    <ol aria-label="Stages in the order they run">
      {lanes.map((lane, i) => {
        const ui = laneStatus(lane);
        const last = i === lanes.length - 1;
        return (
          <motion.li key={lane.index} layout="position" transition={MOTION.base} className="relative flex gap-4 pb-6 last:pb-0">
            {!last && (
              <svg aria-hidden="true" className="absolute left-[15px] top-9 h-[calc(100%-36px)] w-[2px] overflow-visible">
                <line x1="1" y1="0" x2="1" y2="100%" stroke={STATUS[ui === "running" ? "running" : lane.nodes.every((n) => n.ui === "passed") ? "passed" : "queued"].tone} strokeWidth="2" strokeLinecap="round" className={ui === "running" ? "flow" : ""} strokeDasharray={ui === "running" ? undefined : "0"} />
              </svg>
            )}
            <span className={cx("relative z-[1] grid size-8 shrink-0 place-items-center rounded-full bg-surface text-[13px] font-semibold tabular-nums shadow-[inset_0_0_0_1.5px_currentColor]", STATUS[ui].text)} aria-hidden="true">{lane.index}</span>
            <div className="min-w-0 flex-1">
              <h3 className="mb-2 flex items-center gap-2 pt-1 text-[13px] font-medium text-fg-3">{lane.label}{i > 0 && <span className="font-normal">· starts after stage {i}</span>}</h3>
              <div className={cx("grid gap-2", lane.nodes.length > 1 && "sm:grid-cols-2")}>
                {lane.nodes.map((n) => <NodeCard key={n.key} node={n} onOpen={onOpen} />)}
              </div>
            </div>
          </motion.li>
        );
      })}
    </ol>
  );
}

// ------------------------------------------------------------------------------------------------ hub

const PM_WORD: Record<RunView["pm"], string> = {
  idle: "Standing by", planning: "Planning", approval: "Needs your OK", waiting: "Delegated", checking: "Checking results", done: "Finished", stopped: "Needs you",
};

interface Edge { role: string; d: string; to: { x: number; y: number }; from: { x: number; y: number } }

function HubNode({ role, ui, tries, onOpen, nodeRef, align }: { role: string; ui: UiStatus; tries: number; onOpen: (role: string) => void; nodeRef: (el: HTMLButtonElement | null) => void; align: "left" | "right" }) {
  const a = agentToken(role);
  return (
    <button
      ref={nodeRef} type="button" onClick={() => onOpen(role)}
      aria-label={`${a.label}: ${STATUS[ui].label}${tries ? `, ${tries} ${tries === 1 ? "try" : "tries"}` : ""}. Open details.`}
      className={cx("raised flex min-w-0 items-center gap-2 p-2 text-left transition-colors hover:bg-overlay", align === "right" && "flex-row-reverse text-right", ui === "idle" && "opacity-70", ui === "running" && "border-running/50", (ui === "escalated" || ui === "failed") && STATUS[ui].ring)}
    >
      <AgentAvatar role={role} size="sm" live={ui === "running"} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-semibold" title={a.label}>{a.short}</span>
        <span className={cx("flex items-center gap-1 text-[13px]", align === "right" && "justify-end", STATUS[ui].text)}><StatusIcon status={ui} size={14} /><span className="truncate">{STATUS[ui].label}{tries ? ` · ${tries}` : ""}</span></span>
      </span>
    </button>
  );
}

/** The Project Manager in the middle and the ten specialists on either side. Real DOM nodes (so text stays readable) with
 * an SVG layer of edges measured from them. A line means "has been given work"; a flowing line means "working now". */
function Hub({ view, onOpen }: { view: RunView; onOpen: (role: string) => void }) {
  const wrap = useRef<HTMLDivElement>(null);
  const pm = useRef<HTMLDivElement>(null);
  const nodes = useRef<Record<string, HTMLButtonElement | null>>({});
  const [edges, setEdges] = useState<Edge[]>([]);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const reduce = useReducedMotion();
  const left = SPECIALISTS.slice(0, 5), right = SPECIALISTS.slice(5);

  useLayoutEffect(() => {
    const measure = () => {
      const w = wrap.current, c = pm.current;
      if (!w || !c) return;
      const base = w.getBoundingClientRect(), hub = c.getBoundingClientRect();
      setBox({ w: base.width, h: base.height });
      setEdges(SPECIALISTS.flatMap(([role], i) => {
        const el = nodes.current[role];
        if (!el) return [];
        const r = el.getBoundingClientRect();
        const isLeft = i < 5;
        const from = { x: (isLeft ? hub.left : hub.right) - base.left, y: hub.top + hub.height / 2 - base.top };
        const to = { x: (isLeft ? r.right : r.left) - base.left, y: r.top + r.height / 2 - base.top };
        const mid = (from.x + to.x) / 2;
        return [{ role, from, to, d: `M${from.x},${from.y} C${mid},${from.y} ${mid},${to.y} ${to.x},${to.y}` }];
      }));
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (wrap.current) ro.observe(wrap.current);
    return () => ro.disconnect();
  }, [view.tasks.length]);

  const ring = view.check === "pass" ? "var(--passed)" : view.check === "fail" ? "var(--escalated)" : "var(--line)";
  const recent = view.pulses.filter((p) => Date.now() / 1000 - p.ts < 4);
  const column = (list: ReadonlyArray<readonly [string, string]>, align: "left" | "right") => (
    <div className="flex flex-col justify-between gap-2">
      {list.map(([role]) => (
        <HubNode key={role} role={role} ui={agentUi(view, role)} align={align} onOpen={onOpen} nodeRef={(el) => { nodes.current[role] = el; }} tries={Math.max(0, ...view.tasks.filter((t) => t.role === role).map((t) => t.attempt))} />
      ))}
    </div>
  );
  return (
    <div>
      <div ref={wrap} className="relative grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-stretch gap-x-8 sm:gap-x-12">
        <svg aria-hidden="true" width={box.w} height={box.h} viewBox={`0 0 ${box.w || 1} ${box.h || 1}`} className="pointer-events-none absolute inset-0 overflow-visible">
          {edges.map((e) => {
            const ui = agentUi(view, e.role);
            const used = view.tasks.some((t) => t.role === e.role);
            return <path key={e.role} d={e.d} fill="none" stroke={used ? STATUS[ui].tone : "var(--line)"} strokeWidth={ui === "running" ? 2.5 : used ? 2 : 1.25} strokeLinecap="round" opacity={used ? 0.95 : 0.7} className={ui === "running" ? "flow" : ""} strokeDasharray={used || ui === "running" ? undefined : "2 5"} />;
          })}
          {!reduce && recent.map((p) => {
            const e = edges.find((x) => x.role === p.role);
            if (!e) return null;
            const d = p.back ? `M${e.to.x},${e.to.y} C${(e.from.x + e.to.x) / 2},${e.to.y} ${(e.from.x + e.to.x) / 2},${e.from.y} ${e.from.x},${e.from.y}` : e.d;
            return (
              <circle key={p.id} r="5" fill={p.back ? "var(--fg)" : "var(--accent)"} stroke="var(--surface)" strokeWidth="2">
                <animateMotion dur="0.8s" path={d} fill="freeze" />
                <animate attributeName="opacity" values="1;1;0" keyTimes="0;0.8;1" dur="0.8s" fill="freeze" />
              </circle>
            );
          })}
        </svg>
        {column(left, "left")}
        <div className="relative flex items-center">
          <div ref={pm} className="raised relative flex w-[92px] flex-col items-center gap-1.5 p-3 text-center sm:w-[112px]" style={{ boxShadow: `inset 0 0 0 2px ${ring}, var(--shadow)` } as CSSProperties}>
            <AgentAvatar role="project_manager" size="lg" live={isWorking(view)} />
            <span className="text-[13px] font-semibold leading-tight">Project Manager</span>
            <span className="text-[13px] leading-tight text-fg-3">{PM_WORD[view.pm]}</span>
          </div>
        </div>
        {column(right, "right")}
      </div>
      <p className="mt-4 text-[13px] text-fg-3">A line means the specialist has been given work; a flowing line means it is working now. The ring around the Project Manager shows the last result: {view.check ? (view.check === "pass" ? "passed" : "failed") : "none yet"}.</p>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ the tab

type Mode = "stages" | "hub";

/** The Team tab: the dependency swimlane (order, blockers, tries) and the hub view, with a toggle. */
export function TeamView({ view, onOpenAgent }: { view: RunView; onOpenAgent: (role: string) => void }) {
  const [mode, setMode] = useState<Mode>("stages");
  const modes: Array<{ id: Mode; label: string; icon: typeof GitBranch }> = [{ id: "stages", label: "Stages", icon: GitBranch }, { id: "hub", label: "Hub", icon: Network }];
  return (
    <section aria-labelledby="team-title" className="surface p-5">
      <div className="mb-5 flex items-center justify-between gap-3">
        <h2 id="team-title" className="text-[17px] font-semibold tracking-tight">Team</h2>
        <div role="group" aria-label="Team view" className="flex rounded-xl bg-raised p-1">
          {modes.map((m) => (
            <button key={m.id} type="button" aria-pressed={mode === m.id} onClick={() => setMode(m.id)} className={cx("relative inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium transition-colors", mode === m.id ? "text-fg" : "text-fg-3 hover:text-fg-2")}>
              {mode === m.id && <motion.span layoutId="team-mode" transition={MOTION.spring} className="absolute inset-0 rounded-lg bg-overlay shadow-[inset_0_1px_0_var(--highlight),0_1px_2px_rgb(0_0_0/0.3)]" />}
              <m.icon size={14} aria-hidden className="relative" /><span className="relative">{m.label}</span>
            </button>
          ))}
        </div>
      </div>
      {mode === "stages" ? <Swimlane view={view} onOpen={onOpenAgent} /> : <Hub view={view} onOpen={onOpenAgent} />}
    </section>
  );
}
