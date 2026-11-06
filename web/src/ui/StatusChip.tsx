import { RUN_LABEL, runUi, type RunStatus, type UiStatus } from "../model";
import { STATUS } from "../theme/tokens";
import { cx } from "./bits";

/** The status icon: its shape differs for every status, and "running" spins. */
export function StatusIcon({ status, size = 16, className }: { status: UiStatus; size?: number; className?: string }) {
  const Icon = STATUS[status].icon;
  return <Icon size={size} aria-hidden="true" focusable="false" strokeWidth={2.25} className={cx("shrink-0", STATUS[status].spin && "spin", className)} />;
}

const SIZES = {
  sm: "h-6 gap-1 px-2 text-[13px] font-medium",
  md: "h-7 gap-1.5 px-2.5 text-[13px] font-medium",
  lg: "h-9 gap-2 px-3.5 text-[15px] font-semibold",
};

/** Colour + icon + word, with an aria-label, so the status never depends on colour alone. */
export function StatusChip({ status, label, size = "md" }: { status: UiStatus; label?: string; size?: keyof typeof SIZES }) {
  const s = STATUS[status];
  const text = label ?? s.label;
  return (
    <span role="img" aria-label={`Status: ${text}. ${s.aria}`} className={cx("inline-flex shrink-0 items-center whitespace-nowrap rounded-full", SIZES[size], s.chip)}>
      <StatusIcon status={status} size={size === "lg" ? 18 : 14} />
      <span aria-hidden="true">{text}</span>
    </span>
  );
}

export function RunStatusChip({ status, size = "lg" }: { status: RunStatus; size?: keyof typeof SIZES }) {
  return <StatusChip status={runUi(status)} label={RUN_LABEL[status]} size={size} />;
}
