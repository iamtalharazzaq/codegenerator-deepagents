import { useEffect, useReducer, useRef, useState } from "react";

import { applyEvent, emptyRun, type RunEvent, type RunView } from "./model";

type Action = { type: "reset" } | { type: "event"; event: RunEvent };

function reduce(state: RunView, action: Action): RunView {
  return action.type === "reset" ? emptyRun() : applyEvent(state, action.event);
}

/** Subscribes to a run's events. The server replays everything so far, then streams new events and closes the
 * stream when the run finishes. `restart` re-opens it (after a resume) from the last event already seen. */
export function useRunStream(runId: string | null, restart: number): { view: RunView; connected: boolean } {
  const [view, dispatch] = useReducer(reduce, undefined, emptyRun);
  const [connected, setConnected] = useState(false);
  const lastSeq = useRef(0);
  const currentRun = useRef<string | null>(null);

  useEffect(() => {
    if (runId !== currentRun.current) {
      currentRun.current = runId;
      lastSeq.current = 0;
      dispatch({ type: "reset" });
    }
    if (!runId) return;
    const source = new EventSource(`/api/runs/${runId}/events?after=${lastSeq.current}`);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.addEventListener("run_event", (msg) => {
      const event = JSON.parse((msg as MessageEvent<string>).data) as RunEvent;
      if (event.seq <= lastSeq.current) return;
      lastSeq.current = event.seq;
      dispatch({ type: "event", event });
    });
    source.addEventListener("end", () => {
      setConnected(false);
      source.close();
    });
    return () => source.close();
  }, [runId, restart]);

  return { view, connected };
}
