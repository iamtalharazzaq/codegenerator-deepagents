import { nowLine, type RunView } from "../model";
import { StatusIcon, STATUS } from "../ui/Status";

/** The one place that says what is happening right now. */
export function NowLine({ view }: { view: RunView }) {
  const now = nowLine(view);
  if (!now) return null;
  return (
    <p role="status" aria-live="polite" className={`flex items-center gap-2 border-b border-line bg-surface px-4 py-1.5 text-[13px] ${STATUS[now.ui].text}`}>
      <StatusIcon status={now.ui} size={14} />
      <span className="min-w-0 flex-1 truncate">{now.text}</span>
    </p>
  );
}
