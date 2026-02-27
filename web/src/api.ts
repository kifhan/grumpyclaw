export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001/api/v1";

export type ChatMode = "assistant";

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
  createSession: (mode: ChatMode = "assistant", title?: string) =>
    req<{ session_id: string; mode: string; created_at: string }>("/assistant/sessions", {
      method: "POST",
      body: JSON.stringify({ mode, title }),
    }),
  listSessions: () => req<Array<{ id: string; mode: string; title: string; updated_at: string }>>("/assistant/sessions"),
  listMessages: (sessionId: string) => req<Array<{ id: string; role: string; content: string; status: string }>>(`/assistant/sessions/${sessionId}/messages`),
  postMessage: (sessionId: string, content: string) =>
    req<{ message_id: string; queued: boolean }>(`/assistant/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),

  assistantRealtimeStart: () =>
    req<{ ok: boolean; status: Record<string, unknown> }>("/assistant/realtime/start", { method: "POST" }),
  assistantRealtimeStop: () =>
    req<{ ok: boolean; status: Record<string, unknown> }>("/assistant/realtime/stop", { method: "POST" }),
  assistantRealtimeStatus: () =>
    req<{ running: boolean; connected: boolean; thread_alive: boolean; model: string; last_error?: string | null }>("/assistant/realtime/status"),
  assistantRealtimeHistory: (limit = 200) =>
    req<Array<{ id: number; event_type: string; payload: Record<string, unknown>; created_at: string }>>(`/assistant/realtime/history?limit=${limit}`),

  runtimeStatus: () => req<Record<string, unknown>>("/runtime/status"),
  runtimeHeartbeatStart: () => req<Record<string, unknown>>("/runtime/heartbeat/start", { method: "POST" }),
  runtimeHeartbeatStop: () => req<Record<string, unknown>>("/runtime/heartbeat/stop", { method: "POST" }),
  runtimeHeartbeatRunNow: () => req<Record<string, unknown>>("/runtime/heartbeat/run-now", { method: "POST" }),
  robotStatus: () =>
    req<{ run_state: string; robot_connected: boolean; thread_alive: boolean; ts?: string }>("/robot/status"),
  robotStart: () => req<{ ok: boolean; message?: string }>("/robot/start", { method: "POST" }),
  robotStop: () => req<{ ok: boolean; message?: string }>("/robot/stop", { method: "POST" }),
  robotRestart: () => req<{ ok: boolean; message?: string }>("/robot/restart", { method: "POST" }),
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

  devicesAudioStatus: () =>
    req<{ available: boolean; message: string }>("/devices/audio/status"),
  devicesAudioTestSpeaker: () =>
    req<{ ok: boolean; error?: string; message?: string }>("/devices/audio/test-speaker", { method: "POST" }),
  devicesAudioTestMic: () =>
    req<{ ok: boolean; error?: string; message?: string; level?: number; samples?: number }>("/devices/audio/test-mic", { method: "POST" }),
  devicesCamera: () =>
    req<{ ok: boolean; message?: string }>("/devices/camera"),

};

/** Base URL for the API server (no /api/v1). */
export function getApiOrigin(): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001/api/v1";
  return base.replace(/\/api\/v1\/?$/, "") || "http://localhost:8001";
}

export function makeSse(path: string): EventSource {
  const base = API_BASE.replace(/\/api\/v1\/?$/, "");
  return new EventSource(`${base}/api/v1${path}`);
}
