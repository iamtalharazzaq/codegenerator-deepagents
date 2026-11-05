import { nodeState, type RunView } from "../model";
import { SPECIALISTS } from "../roles";

const CX = 320, CY = 260, RX = 245, RY = 190, RIM = 72;
const POS: Record<string, { x: number; y: number }> = Object.fromEntries(
  SPECIALISTS.map(([role], i) => {
    const a = ((-90 + i * 36) * Math.PI) / 180;
    return [role, { x: CX + RX * Math.cos(a), y: CY + RY * Math.sin(a) }];
  }),
);

const PM_WORD: Record<RunView["pm"], string> = {
  idle: "idle", planning: "planning…", replanning: "replanning…", approval: "needs your OK", waiting: "delegated",
  checking: "checking…", done: "finished", stopped: "needs you",
};

/** The Project Manager in the middle, the ten specialists around it. Every working specialist is lit and joined to
 * the centre; the ring is the code-side check of the last result. */
export function Hub({ view }: { view: RunView }) {
  const busy = view.pm === "planning" || view.pm === "replanning";
  const active = new Set(view.tasks.filter((t) => t.status === "in_progress").map((t) => t.role));
  const ring = view.check ?? "";
  const gateWord = view.check === "pass" ? "status: pass" : view.check === "fail" ? "status: fail" : "status check";
  return (
    <svg viewBox="0 30 640 460" role="img" aria-label="Project Manager at the centre with ten specialist agents around it">
      {SPECIALISTS.map(([role]) => (
        <line key={role} className={`spoke ${active.has(role) ? "on" : ""}`} x1={CX} y1={CY} x2={POS[role].x} y2={POS[role].y} />
      ))}
      <circle className={`gate ${ring}`} cx={CX} cy={CY} r={RIM} />
      <circle className={`hub ${busy ? "planning" : ""}`} cx={CX} cy={CY} r={56} />
      <text className="hub-t" x={CX} y={CY - 8}>Project</text>
      <text className="hub-t" x={CX} y={CY + 8}>Manager</text>
      <text className="hub-s" x={CX} y={CY + 25}>{PM_WORD[view.pm]}</text>
      <rect x={CX - 42} y={CY - 94} width={84} height={15} className="gate-bg" />
      <text className={`gate-t ${ring}`} x={CX} y={CY - 83}>{gateWord}</text>
      {SPECIALISTS.map(([role, name]) => {
        const p = POS[role];
        const st = nodeState(view.tasks, role);
        return (
          <g key={role} className={`node ${st.cls}`}>
            <rect x={p.x - 62} y={p.y - 22} width={124} height={44} rx={6} />
            <text className="nm" x={p.x} y={p.y - 3}>{name}</text>
            <text className="st" x={p.x} y={p.y + 12}>{st.word}</text>
          </g>
        );
      })}
      {view.pulses.map((pl) => {
        const end = POS[pl.role];
        if (!end) return null;
        const len = Math.hypot(end.x - CX, end.y - CY);
        const rim = { x: CX + ((end.x - CX) * RIM) / len, y: CY + ((end.y - CY) * RIM) / len };
        const [a, b] = pl.back ? [end, rim] : [rim, end];
        return (
          <circle key={pl.id} className={`pkt ${pl.back ? "back" : ""}`} r={7} cx={a.x} cy={a.y}>
            <animate attributeName="cx" from={a.x} to={b.x} dur="0.7s" fill="freeze" />
            <animate attributeName="cy" from={a.y} to={b.y} dur="0.7s" fill="freeze" />
            <animate attributeName="opacity" values="1;1;0" keyTimes="0;0.8;1" dur="0.7s" fill="freeze" />
          </circle>
        );
      })}
    </svg>
  );
}
