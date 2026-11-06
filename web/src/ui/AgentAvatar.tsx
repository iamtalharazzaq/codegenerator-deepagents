import type { CSSProperties } from "react";

import { agentToken } from "../theme/tokens";
import { cx, LiveDot } from "./bits";

const SIZES = { sm: ["size-7 rounded-lg", 14], md: ["size-9 rounded-xl", 18], lg: ["size-12 rounded-2xl", 24] } as const;

/** An agent's identity: its icon in a tinted rounded square, in the hue that agent has everywhere in the app. */
export function AgentAvatar({ role, size = "md", live = false, className }: { role: string; size?: keyof typeof SIZES; live?: boolean; className?: string }) {
  const a = agentToken(role);
  const [box, icon] = SIZES[size];
  return (
    <span className={cx("agent-tint relative inline-flex shrink-0 items-center justify-center", box, className)} style={{ "--agent-h": a.hue } as CSSProperties} role="img" aria-label={a.label}>
      <a.icon size={icon} strokeWidth={2} aria-hidden="true" />
      {live && <span className="absolute -right-0.5 -top-0.5 rounded-full bg-surface p-0.5"><LiveDot /></span>}
    </span>
  );
}
