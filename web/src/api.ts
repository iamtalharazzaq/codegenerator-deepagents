export interface RunRow {
  run_id: string;
  project: string;
  request: string;
  status: string;
  /** "plan" or "review" while the run is waiting for the person; null otherwise */
  waiting_for?: "plan" | "review" | null;
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

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  kind: "" | "plan";
  ts: number;
}

export interface Chat {
  id: string;
  title: string;
  messages: ChatMessage[];
  project: string | null;
  run_ids: string[];
}

export interface ChatRow {
  id: string;
  title: string;
  updated_at: number;
  messages: number;
  project: string | null;
  runs: number;
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
  chats: () => call<ChatRow[]>("/api/chats"),
  chat: (id: string) => call<Chat>(`/api/chats/${id}`),
  newChat: (project?: string | null) => post<Chat>("/api/chats", project ? { project } : {}),
  /** `plan`: answer with the plan in key points (the first message of a conversation asks for it) */
  say: (id: string, text: string, plan = false) => post<Chat>(`/api/chats/${id}/messages`, { text, plan }),
  draftPlan: (id: string) => post<Chat>(`/api/chats/${id}/plan`),
  build: (id: string, body: { plan_approval: boolean; final_review: boolean; concurrency?: number }) => post<{ run_id: string; project: string }>(`/api/chats/${id}/build`, body),
  start: (body: StartBody) => post<{ run_id: string; project: string }>("/api/runs", body),
  review: (id: string, accept: boolean, changes: string) => post<{ ok: boolean }>(`/api/runs/${id}/review`, { accept, changes }),
  /** Approve the plan, send it back with changes (not approved + feedback), or reject it (not approved, no feedback). */
  approve: (id: string, approved: boolean, feedback = "") => post<{ ok: boolean }>(`/api/runs/${id}/approve`, { approved, feedback: feedback || null }),
  resume: (id: string, guidance: string) => post<{ run_id: string }>(`/api/runs/${id}/resume`, { guidance: guidance || null }),
  cancel: (id: string) => post<{ ok: boolean }>(`/api/runs/${id}/cancel`),
  report: async (id: string): Promise<{ report: string | null; has_zip: boolean }> => call(`/api/runs/${id}`),
  file: async (id: string, path: string): Promise<string> => {
    const res = await fetch(`/api/runs/${id}/files/${path.split("/").map(encodeURIComponent).join("/")}`);
    if (!res.ok) throw new Error("That file is not available to preview.");
    return res.text();
  },
  artifact: async (id: string, name: string): Promise<string> => {
    const res = await fetch(`/api/runs/${id}/artifacts/${name}`);
    if (!res.ok) throw new Error("The result file is not there.");
    return res.text();
  },
};
