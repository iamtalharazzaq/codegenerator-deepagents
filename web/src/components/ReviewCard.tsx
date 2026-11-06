import { PackageCheck } from "lucide-react";
import { useState } from "react";

import type { Review } from "../model";
import { Button, Clamp } from "../ui/bits";
import { Markdown } from "../ui/Markdown";

/** The last stop before delivery: the work passed, the zip is not built yet. Deliver it, or say what should change and
 * the Project Manager does that work and asks again. */
export function ReviewCard({ review, onDecide }: { review: Review; onDecide: (accept: boolean, changes: string) => void }) {
  const [changes, setChanges] = useState("");
  const shown = review.files.slice(0, 12);
  return (
    <section aria-labelledby="review-title" className="raised border-passed/40 bg-[radial-gradient(520px_200px_at_0%_0%,color-mix(in_srgb,var(--passed)_12%,transparent),transparent_70%),var(--raised)] p-5">
      <h2 id="review-title" className="flex items-center gap-2 text-[17px] font-semibold tracking-tight text-passed"><PackageCheck size={20} aria-hidden />Ready to deliver{review.round > 1 ? ` (review ${review.round})` : ""}</h2>
      <p className="mt-1 text-fg-2">Everything passed. The zip is not built yet: look over the result first.</p>
      {review.summary && <Clamp lines={4} className="mt-3"><Markdown text={review.summary} /></Clamp>}
      {review.files.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-[13px] font-medium text-accent">Files in the zip ({review.files.length})</summary>
          <ul className="mt-2 space-y-0.5 font-mono text-[13px] text-fg-2">
            {shown.map((f) => <li key={f}>{f}</li>)}
            {review.files.length > shown.length && <li className="text-fg-3">and {review.files.length - shown.length} more</li>}
          </ul>
        </details>
      )}
      <label htmlFor="review-changes" className="mt-4 block text-[13px] font-semibold">Anything to change before delivery?</label>
      <textarea id="review-changes" rows={2} value={changes} onChange={(e) => setChanges(e.target.value)} placeholder="For example: add a README, or also handle negative numbers."
        className="mt-1 w-full resize-y rounded-xl border border-control bg-page px-3 py-2 text-fg placeholder:text-fg-3" />
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => onDecide(true, "")}>Deliver the zip</Button>
        <Button disabled={!changes.trim()} onClick={() => onDecide(false, changes.trim())}>Request changes</Button>
      </div>
      <p className="mt-2 text-[13px] text-fg-3">{changes.trim() ? "Requesting changes sends your note to the Project Manager. It does the extra work and asks you again." : "Write what should change to enable Request changes."}</p>
    </section>
  );
}
