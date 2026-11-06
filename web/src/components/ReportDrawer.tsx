import { useEffect, useState } from "react";

import { useData } from "../data";
import { Skeleton } from "../ui/bits";
import { Drawer } from "../ui/Drawer";
import { Markdown } from "../ui/Markdown";

/** The full run report, loaded when the drawer opens. */
export function ReportDrawer({ runId, open, onClose }: { runId: string | null; open: boolean; onClose: () => void }) {
  const source = useData();
  const [report, setReport] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    if (!open || !runId) return;
    let live = true;
    setReport(undefined);
    source.report(runId).then((r) => live && setReport(r ?? "")).catch(() => live && setReport(null));
    return () => { live = false; };
  }, [open, runId, source]);
  return (
    <Drawer open={open} onClose={onClose} title="Full report" subtitle={runId ? <span className="font-mono">{runId}</span> : undefined} width="max-w-[760px]">
      {report === undefined ? <div className="space-y-3" aria-busy="true"><Skeleton className="h-6 w-1/2" /><Skeleton className="h-4" /><Skeleton className="h-4 w-5/6" /><Skeleton className="h-32" /></div>
        : report === null ? <p className="text-fg-2">The report is not available.</p>
        : report === "" ? <p className="text-fg-2">No report was written.</p>
        : <Markdown text={report} />}
    </Drawer>
  );
}
