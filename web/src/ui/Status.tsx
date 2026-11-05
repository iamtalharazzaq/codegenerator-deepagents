import type { ReactNode } from "react";

import { RUN_LABEL, runUi, type RunStatus, type UiStatus } from "../model";

/** The one status system: a colour, an icon shape and a word. The word and the shape carry the meaning, so nothing
 * depends on colour alone. Class names are written out in full so Tailwind can see them. */
export const STATUS: Record<UiStatus, { label: string; chip: string; text: string; ring: string; token: string }> = {
  passed: { label: "Passed", chip: "bg-passed-bg text-passed", text: "text-passed", ring: "border-passed/50", token: "var(--color-passed)" },
  running: { label: "Running", chip: "bg-running-bg text-running", text: "text-running", ring: "border-running/60", token: "var(--color-running)" },
  queued: { label: "Queued", chip: "bg-queued-bg text-queued", text: "text-queued", ring: "border-line", token: "var(--color-queued)" },
  blocked: { label: "Blocked", chip: "bg-blocked-bg text-blocked", text: "text-blocked", ring: "border-blocked/50", token: "var(--color-blocked)" },
  failed: { label: "Failed", chip: "bg-failed-bg text-failed", text: "text-failed", ring: "border-failed/50", token: "var(--color-failed)" },
  escalated: { label: "Escalated", chip: "bg-escalated-bg text-escalated", text: "text-escalated", ring: "border-escalated/60", token: "var(--color-escalated)" },
  idle: { label: "Idle", chip: "bg-idle-bg text-idle", text: "text-idle", ring: "border-line", token: "var(--color-idle)" },
};

const ICONS: Record<UiStatus, ReactNode> = {
  passed: <path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />,
  running: <path d="M8 2.5a5.5 5.5 0 1 1-5.5 5.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="spin" />,
  queued: <><circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.8" /><path d="M8 5v3.4l2.2 1.3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></>,
  blocked: <><circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.8" /><path d="M4.6 11.4l6.8-6.8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></>,
  failed: <path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />,
  escalated: <><path d="M8 2.2l6.2 11H1.8l6.2-11z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /><path d="M8 6.6v3M8 11.6v.1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></>,
  idle: <path d="M4 8h8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />,
};

export function StatusIcon({ status, size = 16 }: { status: UiStatus; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" focusable="false" className="shrink-0">
      {ICONS[status]}
    </svg>
  );
}

export function StatusChip({ status, label, size = "md" }: { status: UiStatus; label?: string; size?: "sm" | "md" | "lg" }) {
  const s = STATUS[status];
  const text = label ?? s.label;
  const sizing = size === "lg" ? "px-3 py-1.5 text-base gap-2 font-semibold" : size === "sm" ? "px-1.5 py-0.5 text-[13px] gap-1 font-medium" : "px-2 py-0.5 text-[13px] gap-1.5 font-medium";
  return (
    <span className={`inline-flex items-center rounded-md ${sizing} ${s.chip}`} aria-label={`Status: ${text}`} role="img">
      <StatusIcon status={status} size={size === "lg" ? 18 : 14} />
      <span aria-hidden="true">{text}</span>
    </span>
  );
}

export function RunStatusChip({ status, size = "lg" }: { status: RunStatus; size?: "sm" | "md" | "lg" }) {
  return <StatusChip status={runUi(status)} label={RUN_LABEL[status]} size={size} />;
}
