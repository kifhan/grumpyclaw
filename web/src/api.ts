const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export type ChatMode = "grumpyclaw" | "grumpyreachy";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json() as Promise<T>;
}

export const api = {
  createSession: (mode: ChatMode, title?: string) =>
    req<{ session_id: string; mode: ChatMode; created_at: string }>("/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ mode, title }),
    }),
  listSessions: () => req<Array<{ id: string; mode: ChatMode; title: string; updated_at: string }>>("/chat/sessions"),
  listMessages: (sessionId: string) => req<Array<{ id: string; role: string; content: string; status: string }>>(`/chat/sessions/${sessionId}/messages`),
  postMessage: (sessionId: string, content: string) =>
    req<{ message_id: string; queued: boolean }>(`/chat/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  runtimeStatus: () => req<Record<string, unknown>>("/runtime/status"),
  runtimeAction: (name: string, action: "start" | "stop" | "restart") =>
    req(`/runtime/processes/${name}/${action}`, { method: "POST" }),
  robotAction: (payload: Record<string, unknown>) => req("/robot/actions", { method: "POST", body: JSON.stringify(payload) }),
  searchMemory: (q: string, topK = 5) => req(`/memory/search?q=${encodeURIComponent(q)}&top_k=${topK}`),
  listSkills: () => req<Array<{ id: string; name: string; preview: string }>>("/skills"),
  runSkill: (skillId: string) => req<{ skill_id: string; content: string }>("/skills/run", { method: "POST", body: JSON.stringify({ skill_id: skillId }) }),
  evaluateHeartbeat: () => req("/heartbeat/evaluate", { method: "POST" }),
  heartbeatHistory: () => req<Array<Record<string, unknown>>>("/heartbeat/history"),
  logs: (filters?: {
    source?: string;
    level?: string;
    process_name?: string;
    event_type?: string;
    q?: string;
    limit?: number;
  }) => {
    const params = new URLSearchParams();
    if (filters?.source) params.set("source", filters.source);
    if (filters?.level) params.set("level", filters.level);
    if (filters?.process_name) params.set("process_name", filters.process_name);
    if (filters?.event_type) params.set("event_type", filters.event_type);
    if (filters?.q) params.set("q", filters.q);
    if (filters?.limit) params.set("limit", String(filters.limit));
    const suffix = params.size > 0 ? `?${params.toString()}` : "";
    return req<{ items: Array<Record<string, unknown>> }>(`/logs${suffix}`);
  },
  health: () => req<{ status: string }>("/healthz"),
};

export function makeSse(path: string): EventSource {
  const base = API_BASE.replace(/\/api\/v1\/?$/, "");
  return new EventSource(`${base}/api/v1${path}`);
}
