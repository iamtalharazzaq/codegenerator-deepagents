import { ArrowUp, ClipboardList, Hammer, MessageCircleMore, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { Chat } from "../api";
import { AgentAvatar } from "../ui/AgentAvatar";
import { Button, cx, LiveDot } from "../ui/bits";
import { Toggle } from "../ui/Controls";
import { Markdown } from "../ui/Markdown";

interface Props {
  chat: Chat | null;
  /** the Project Manager is answering */
  thinking: boolean;
  /** resolves false when the message could not be sent, so the box keeps what was typed */
  onSend: (text: string) => Promise<boolean>;
  onPlan: () => void;
  onBuild: (planApproval: boolean, finalReview: boolean) => void;
  /** the "Review before the zip" choice made where the conversation was started */
  defaultReview?: boolean;
  onOpenRun: (id: string) => void;
  onLeave: () => void;
}

const STARTERS = [
  "I need a small tool that converts units. What should I build first?",
  "Help me turn this problem into a plan: our team loses track of tasks.",
  "I have an idea for a to-do web page. Suggest what it should do.",
];

/** Talk first: a conversation with the Project Manager before any work starts. It asks, suggests and, when asked, drafts
 * a plan; nothing is built here. "Build this" starts a normal run from what was agreed (which shows its plan again). */
export function ChatPane({ chat, thinking, onSend, onPlan, onBuild, defaultReview = true, onOpenRun, onLeave }: Props) {
  const [text, setText] = useState("");
  const [approve, setApprove] = useState(false); // the plan was just shown here; ask again only if you want to
  const [review, setReview] = useState(defaultReview);
  const log = useRef<HTMLDivElement>(null);
  const messages = chat?.messages ?? [];
  const hasPlan = messages.some((m) => m.kind === "plan");
  const said = messages.some((m) => m.role === "user");
  const last = messages[messages.length - 1];

  useEffect(() => {
    const el = log.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, [messages.length, thinking]);

  const send = async () => {
    const t = text.trim();
    if (!t || thinking) return;
    setText("");
    if (!(await onSend(t))) setText(t);
  };

  return (
    <section aria-label="Talk it through" className="surface flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-hairline px-4 py-3">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold"><MessageCircleMore size={18} aria-hidden className="text-accent" />Talk it through</h2>
        <Button variant="ghost" size="sm" onClick={onLeave}><Play size={14} aria-hidden />New request</Button>
      </div>

      <div ref={log} role="log" aria-live="polite" aria-label="Conversation" className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="rounded-2xl border border-hairline bg-raised p-4">
            <p className="font-semibold">Tell me what you want built, or the problem to solve.</p>
            <p className="mt-1 text-[13px] text-fg-2">I'll answer with a plan in key points, suggest the smallest thing that works, and ask only what would change it. Nothing is built until you say so.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {STARTERS.map((s) => <button key={s} type="button" onClick={() => setText(s)} className="rounded-xl border border-hairline bg-page px-3 py-1.5 text-left text-[13px] text-fg-2 hover:text-fg">{s}</button>)}
            </div>
          </div>
        )}
        {messages.map((m, i) => m.role === "user" ? (
          <div key={i} className="flex justify-end"><p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-[var(--accent-from)] px-4 py-2.5 text-on-accent">{m.text}</p></div>
        ) : (
          <div key={i} className="flex gap-3">
            <AgentAvatar role="project_manager" size="sm" />
            <div className="min-w-0 max-w-[92%] flex-1">
              <p className="text-[13px] font-semibold text-fg-2">Project Manager{m.kind === "plan" && <span className="ml-2 rounded-full bg-accent/15 px-2 py-0.5 text-accent">Proposed plan</span>}</p>
              <div className={cx("mt-1 break-words", m.kind === "plan" && "rounded-2xl border border-accent/30 bg-raised p-3")}><Markdown text={m.text} /></div>
            </div>
          </div>
        ))}
        {thinking && <p className="flex items-center gap-2 text-[13px] text-fg-2"><LiveDot />Project Manager is thinking…</p>}
        {chat && chat.run_ids.length > 0 && (
          <p className="text-[13px] text-fg-3">Runs from this conversation: {chat.run_ids.map((id) => <button key={id} type="button" onClick={() => onOpenRun(id)} className="mr-2 underline hover:text-fg">{id}</button>)}</p>
        )}
      </div>

      <div className="border-t border-hairline p-4">
        {hasPlan && (
          <div className="mb-3 grid gap-2 sm:grid-cols-2">
            <Toggle checked={approve} onChange={setApprove} title="Approve the plan first" hint="The run shows its detailed plan again before it starts." />
            <Toggle checked={review} onChange={setReview} title="Review before the zip" hint="You can ask for changes before the zip is built." />
          </div>
        )}
        <label htmlFor="chat-input" className="sr-only">Message to the Project Manager</label>
        <textarea
          id="chat-input" rows={2} value={text} onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void send(); } }}
          placeholder={messages.length ? "Answer, ask a question, or ask for changes…" : "Describe the problem or the idea…"}
          className="w-full resize-none rounded-2xl border border-control bg-page px-4 py-3 text-[15px] text-fg placeholder:text-fg-3"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <span className="text-[13px] text-fg-3">Ctrl+Enter to send</span>
          <div className="flex flex-wrap gap-2">
            <Button onClick={onPlan} disabled={!said || thinking}><ClipboardList size={16} aria-hidden />{hasPlan ? "Draft the plan again" : "Draft the plan"}</Button>
            <Button variant="primary" onClick={() => onBuild(approve, review)} disabled={!hasPlan || thinking}><Hammer size={16} aria-hidden />Build this</Button>
            <Button variant="primary" onClick={() => void send()} disabled={!text.trim() || thinking}><ArrowUp size={16} aria-hidden />Send</Button>
          </div>
        </div>
        {!hasPlan && said && last?.role === "assistant" && <p className="mt-2 text-[13px] text-fg-3">When you are happy with the idea, Draft the plan. Build this unlocks once you have seen a plan.</p>}
      </div>
    </section>
  );
}
