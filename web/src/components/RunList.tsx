import type { RunRow } from "../api";

export function RunList({ runs, selected, onSelect, onNew }: { runs: RunRow[]; selected: string | null; onSelect: (id: string) => void; onNew: () => void }) {
  return (
    <aside className="pane runs">
      <button className="btn primary wide" onClick={onNew}>New run</button>
      <div className="eyebrow">RUNS</div>
      {runs.length === 0 && <p className="muted">No runs yet.</p>}
      {runs.map((r) => (
        <button key={r.run_id} className={`run-item ${r.run_id === selected ? "on" : ""}`} onClick={() => onSelect(r.run_id)}>
          <span className="run-title">{r.request || r.run_id}</span>
          <small>{r.status}{r.tasks_total ? ` · ${r.tasks_done}/${r.tasks_total} tasks` : ""}</small>
        </button>
      ))}
    </aside>
  );
}
