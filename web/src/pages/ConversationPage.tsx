import { useCallback, useEffect, useMemo, useState } from "react";
import { api, makeSse } from "../api";

type TimelineEntry = {
  id: string;
  ts: string;
  kind: "transcript" | "tool" | "status";
  label: string;
  content: string;
};

export function ConversationPage() {
  const [status, setStatus] = useState<{
    running: boolean;
    thread_alive: boolean;
    connected: boolean;
    model: string;
    last_error?: string | null;
  } | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [busy, setBusy] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const s = await api.assistantRealtimeStatus();
      setStatus(s);
    } catch {
      setStatus(null);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const rows = await api.assistantRealtimeHistory(200);
      const mapped = rows.map((row) => {
        const payload = row.payload as Record<string, unknown>;
        const ts = String(payload.ts ?? row.created_at ?? "");
        if (row.event_type === "assistant.realtime.transcript") {
          return {
            id: String(row.id),
            ts,
            kind: "transcript" as const,
            label: String(payload.role ?? "transcript"),
            content: String(payload.content ?? ""),
          };
        }
        if (row.event_type === "assistant.tool") {
          return {
            id: String(row.id),
            ts,
            kind: "tool" as const,
            label: String(payload.name ?? "tool"),
            content: JSON.stringify(payload.result ?? payload),
          };
        }
        return {
          id: String(row.id),
          ts,
          kind: "status" as const,
          label: "status",
          content: JSON.stringify(payload),
        };
      });
      setTimeline(mapped);
    } catch {
      setTimeline([]);
    }
  }, []);

  useEffect(() => {
    loadStatus();
    loadHistory();
  }, [loadStatus, loadHistory]);

  useEffect(() => {
    const stream = makeSse("/assistant/realtime/stream");

    stream.addEventListener("assistant.realtime.transcript", (e) => {
      const payload = JSON.parse((e as MessageEvent).data) as { role?: string; content?: string; ts?: string };
      setTimeline((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          ts: payload.ts ?? new Date().toISOString(),
          kind: "transcript",
          label: payload.role ?? "transcript",
          content: payload.content ?? "",
        },
      ]);
    });

    stream.addEventListener("assistant.tool", (e) => {
      const payload = JSON.parse((e as MessageEvent).data) as { name?: string; result?: unknown; ts?: string };
      setTimeline((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          ts: payload.ts ?? new Date().toISOString(),
          kind: "tool",
          label: payload.name ?? "tool",
          content: JSON.stringify(payload.result ?? payload),
        },
      ]);
    });

    stream.addEventListener("assistant.realtime.status", () => {
      loadStatus().catch(() => undefined);
    });

    return () => stream.close();
  }, [loadStatus]);

  const ordered = useMemo(() => [...timeline].sort((a, b) => a.ts.localeCompare(b.ts)), [timeline]);

  async function startRealtime() {
    setBusy(true);
    try {
      await api.assistantRealtimeStart();
      await loadStatus();
    } finally {
      setBusy(false);
    }
  }

  async function stopRealtime() {
    setBusy(true);
    try {
      await api.assistantRealtimeStop();
      await loadStatus();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h2>Conversation</h2>
      <div className="panel">
        <h4>Realtime status</h4>
        <pre>{status ? JSON.stringify(status, null, 2) : "Unavailable"}</pre>
        <div className="row">
          <button onClick={startRealtime} disabled={busy || !!status?.running}>Start Realtime</button>
          <button onClick={stopRealtime} disabled={busy || !status?.running}>Stop Realtime</button>
          <button onClick={() => loadHistory().catch(() => undefined)} disabled={busy}>Reload History</button>
        </div>
      </div>

      <div className="panel">
        <h4>Server-side transcript and tool timeline</h4>
        {ordered.length === 0 ? (
          <p style={{ color: "var(--color-muted, #666)" }}>No events yet.</p>
        ) : (
          ordered.map((item) => (
            <div key={item.id} style={{ marginBottom: 8 }}>
              <strong>{item.label}</strong> <span style={{ color: "var(--color-muted, #666)" }}>{item.ts}</span>
              <div>{item.content}</div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
