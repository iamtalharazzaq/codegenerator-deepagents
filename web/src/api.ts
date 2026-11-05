export interface RunRow {
  run_id: string;
  project: string;
  request: string;
  status: string;
  reason: string | null;
  created_at: number;
  tasks_done: number;
  tasks_total: number;
}

export interface ProjectRow {
  name: string;
  runs: number;
  last_run_at: number;
}

export interface AppConfig {
  default_project: string | null;
  concurrency: number;
  demo: boolean;
}

export interface StartBody {
  request: string;
  project?: string;
  plan_approval: boolean;
  final_review?: boolean;
  concurrency?: number;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) => call<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });

export const api = {
  config: () => call<AppConfig>("/api/config"),
  runs: () => call<RunRow[]>("/api/runs"),
  projects: () => call<ProjectRow[]>("/api/projects"),
  start: (body: StartBody) => post<{ run_id: string; project: string }>("/api/runs", body),
  review: (id: string, accept: boolean, changes: string) => post<{ ok: boolean }>(`/api/runs/${id}/review`, { accept, changes }),
  approve: (id: string, approved: boolean) => post<{ ok: boolean }>(`/api/runs/${id}/approve`, { approved }),
  resume: (id: string, guidance: string) => post<{ run_id: string }>(`/api/runs/${id}/resume`, { guidance: guidance || null }),
  cancel: (id: string) => post<{ ok: boolean }>(`/api/runs/${id}/cancel`),
  report: async (id: string): Promise<{ report: string | null; has_zip: boolean }> => call(`/api/runs/${id}`),
  artifact: async (id: string, name: string): Promise<string> => {
    const res = await fetch(`/api/runs/${id}/artifacts/${name}`);
    if (!res.ok) throw new Error("The result file is not there.");
    return res.text();
  },
};
