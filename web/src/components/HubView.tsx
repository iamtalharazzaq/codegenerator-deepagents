import { agentUi, type RunView } from "../model";
import { SPECIALISTS } from "../roles";
import { STATUS } from "../ui/Status";

const CX = 380, CY = 270, RX = 292, RY = 200, RIM = 78;
const W = 172, H = 54;
const POS: Record<string, { x: number; y: number }> = Object.fromEntries(
  SPECIALISTS.map(([role], i) => {
    const a = ((-90 + i * 36) * Math.PI) / 180;
    return [role, { x: CX + RX * Math.cos(a), y: CY + RY * Math.sin(a) }];
  }),
);
const PM_WORD: Record<RunView["pm"], string> = {
  idle: "idle", planning: "planning", approval: "needs your OK", waiting: "delegated", checking: "checking results", done: "finished", stopped: "needs you",
};

/** The Project Manager in the middle and the ten specialists around it. A line means "has been given work"; a moving
 * line means "working now". Click a specialist for its details. */
export function HubView({ view, onOpen }: { view: RunView; onOpen: (role: string) => void }) {
  const ring = view.check === "pass" ? "var(--color-passed)" : view.check === "fail" ? "var(--color-escalated)" : "var(--color-line)";
  return (
    <div className="p-2">
      <svg viewBox="0 20 760 500" role="group" aria-label="Project Manager and the ten specialist agents" className="mx-auto block w-full max-w-[640px]">
        {SPECIALISTS.map(([role]) => {
          const ui = agentUi(view, role);
          const p = POS[role];
          const used = view.tasks.some((t) => t.role === role);
          return <line key={role} x1={CX} y1={CY} x2={p.x} y2={p.y} stroke={used ? STATUS[ui].token : "var(--color-line)"} strokeWidth={ui === "running" ? 3 : used ? 2 : 1} className={ui === "running" ? "march" : ""} opacity={used ? 0.9 : 0.5} />;
        })}
        <circle cx={CX} cy={CY} r={RIM} fill="none" stroke={ring} strokeWidth={view.check ? 5 : 2} strokeDasharray={view.check ? undefined : "3 7"} />
        <circle cx={CX} cy={CY} r={60} fill="var(--color-raised)" stroke="var(--color-line)" strokeWidth={1.5} />
        <text x={CX} y={CY - 10} textAnchor="middle" fontSize="14" fontWeight="600" fill="var(--color-fg)">Project</text>
        <text x={CX} y={CY + 8} textAnchor="middle" fontSize="14" fontWeight="600" fill="var(--color-fg)">Manager</text>
        <text x={CX} y={CY + 28} textAnchor="middle" fontSize="13" fill="var(--color-fg-2)">{PM_WORD[view.pm]}</text>
        <text x={CX} y={CY - RIM - 8} textAnchor="middle" fontSize="13" fill="var(--color-fg-2)">{view.check ? `last result: ${view.check === "pass" ? "passed" : "failed"}` : "no result yet"}</text>
        {SPECIALISTS.map(([role, name]) => {
          const ui = agentUi(view, role);
          const p = POS[role];
          const tries = Math.max(0, ...view.tasks.filter((t) => t.role === role).map((t) => t.attempt));
          const s = STATUS[ui];
          return (
            <g key={role} role="button" tabIndex={0} aria-label={`${name}: ${s.label}${tries ? `, ${tries} ${tries === 1 ? "try" : "tries"}` : ""}. Open details.`}
              onClick={() => onOpen(role)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(role); } }} className="cursor-pointer outline-none [&:focus-visible>rect]:stroke-[var(--color-accent)] [&:focus-visible>rect]:stroke-[3]">
              <rect x={p.x - W / 2} y={p.y - H / 2} width={W} height={H} rx={10} fill="var(--color-raised)" stroke={s.token} strokeWidth={ui === "idle" ? 1 : 2} strokeDasharray={ui === "queued" || ui === "blocked" ? "5 4" : undefined} />
              <text x={p.x} y={p.y - 4} textAnchor="middle" fontSize="13" fontWeight="600" fill="var(--color-fg)">{name}</text>
              <text x={p.x} y={p.y + 14} textAnchor="middle" fontSize="13" fill={s.token}>{s.label}{tries ? ` · try ${tries}` : ""}</text>
            </g>
          );
        })}
        {view.pulses.filter((pl) => Date.now() / 1000 - pl.ts < 4).map((pl) => {
          const end = POS[pl.role];
          if (!end) return null;
          const len = Math.hypot(end.x - CX, end.y - CY);
          const rim = { x: CX + ((end.x - CX) * RIM) / len, y: CY + ((end.y - CY) * RIM) / len };
          const [a, b] = pl.back ? [end, rim] : [rim, end];
          return (
            <circle key={pl.id} r={7} cx={a.x} cy={a.y} fill={pl.back ? "var(--color-fg)" : "var(--color-accent)"} stroke="var(--color-page)" strokeWidth={2}>
              <animate attributeName="cx" from={a.x} to={b.x} dur="0.7s" fill="freeze" />
              <animate attributeName="cy" from={a.y} to={b.y} dur="0.7s" fill="freeze" />
              <animate attributeName="opacity" values="1;1;0" keyTimes="0;0.8;1" dur="0.7s" fill="freeze" />
            </circle>
          );
        })}
      </svg>
      <p className="px-2 text-[13px] text-fg-3">A line means the specialist has been given work; a moving line means it is working now. The Project Manager decides the order.</p>
    </div>
  );
}
