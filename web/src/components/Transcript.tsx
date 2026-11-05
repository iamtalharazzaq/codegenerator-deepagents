import { useEffect, useRef } from "react";

import type { ChatItem, RunView } from "../model";
import { taskUi } from "../model";
import { roleLabel } from "../roles";
import { Clamp } from "../ui/bits";
import { StatusChip, StatusIcon, STATUS } from "../ui/Status";

/** The conversation. Long reasoning is collapsed, results are one compact timeline row each, and guardrail hits sit
 * on the task they belong to instead of floating as banners. */
export function Transcript({ view, onOpenAgent, onLogs }: { view: RunView; onOpenAgent: (role: string, taskId?: string) => void; onLogs: (taskId?: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // scroll only this list (scrollIntoView would also scroll the page)
    const toEnd = () => box.current?.scrollTo({ top: box.current.scrollHeight });
    toEnd();
    const frame = requestAnimationFrame(toEnd); // again once "Show more" clamps have measured themselves
    return () => cancelAnimationFrame(frame);
  }, [view.chat.length]);

  const row = (m: ChatItem, i: number) => {
    switch (m.kind) {
      case "user":
        return <li key={i} className="flex justify-end"><p className="max-w-[92%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-raised px-3 py-2">{m.text}</p></li>;
      case "pm":
        return (
          <li key={i}>
            <p className="text-[13px] font-semibold text-accent">Project Manager</p>
            <Clamp lines={3} className="mt-0.5 text-fg"><p className="whitespace-pre-wrap break-words">{m.text}</p></Clamp>
          </li>
        );
      case "todo":
        return <li key={i} className="flex items-center gap-2 text-[13px] text-fg-2"><svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M3 4h10M3 8h10M3 12h6" /></svg>{m.text}</li>;
      case "result": {
        const task = view.tasks.find((t) => t.id === m.taskId);
        const ui = task ? taskUi(view, task) : m.ok ? "passed" : "failed";
        const hits = task?.guardrails.length ?? 0;
        return (
          <li key={i}>
            <div className="flex gap-3">
              <span className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full ${STATUS[ui].chip}`}><StatusIcon status={ui} size={14} /></span>
              <div className="min-w-0 flex-1">
                <button type="button" onClick={() => onOpenAgent(m.role, m.taskId)} className="flex w-full flex-wrap items-baseline gap-x-2 text-left hover:underline">
                  <span className="font-semibold">{roleLabel(m.role)}</span>
                  <span className={STATUS[ui].text}>{m.ok ? "passed" : ui === "escalated" ? "escalated" : "failed"}</span>
                  <span className="text-[13px] text-fg-3">try {m.attempt}</span>
                </button>
                <p className="mt-0.5 truncate font-mono text-[13px] text-fg-2" title={m.reason}>{m.reason || "No reason given."}</p>
                {hits > 0 && (
                  <button type="button" onClick={() => onLogs(m.taskId)} className="mt-1 inline-flex items-center gap-1 rounded-md bg-blocked-bg px-2 py-0.5 text-[13px] font-medium text-blocked hover:brightness-125" aria-label={`${hits} guardrail hit${hits > 1 ? "s" : ""} on this task. Open the log.`}>
                    <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor"><path d="M3 2v12h1.5V9h8l-2-3.5 2-3.5H3z" /></svg>
                    {hits} guardrail hit{hits > 1 ? "s" : ""}
                  </button>
                )}
              </div>
            </div>
          </li>
        );
      }
      case "note":
        return <li key={i} className={`rounded-lg px-3 py-2 text-[13px] ${m.tone === "warn" ? "bg-blocked-bg text-blocked" : "bg-raised text-fg-2"}`}>{m.text}</li>;
      case "run":
        return (
          <li key={i} className={`rounded-xl border p-3 ${m.ok ? STATUS.passed.ring : STATUS.escalated.ring}`}>
            <p className={`flex items-center gap-2 font-semibold ${m.ok ? "text-passed" : "text-escalated"}`}><StatusIcon status={m.ok ? "passed" : "escalated"} size={16} />{m.title}</p>
            <p className="mt-1 text-fg-2">{m.text}</p>
            {m.summary && <Clamp lines={3} className="mt-1 text-fg"><p>{m.summary}</p></Clamp>}
          </li>
        );
    }
  };

  if (!view.chat.length) {
    return (
      <div className="flex-1 overflow-y-auto p-4 text-fg-2">
        <p className="text-base font-semibold text-fg">What should be built?</p>
        <p className="mt-2 max-w-[48ch]">Describe the change. The Project Manager writes a to-do list, hands each task to the right specialist, reads every result, and decides what to do next.</p>
      </div>
    );
  }
  return (
    <div ref={box} className="flex-1 overflow-y-auto p-4" tabIndex={0} aria-label="Conversation">
      <ol className="space-y-4">{view.chat.map(row)}</ol>
    </div>
  );
}

export { StatusChip };
