import { useEffect, useState } from "react";
import { api } from "../api";

export function HeartbeatPage() {
  const [latest, setLatest] = useState<Record<string, unknown> | null>(null);
  const [history, setHistory] = useState<Array<Record<string, unknown>>>([]);

  async function refresh() {
    setHistory(await api.heartbeatHistory());
  }

  useEffect(() => {
    refresh().catch(console.error);
  }, []);

  async function run() {
    const out = (await api.evaluateHeartbeat()) as Record<string, unknown>;
    setLatest(out);
    await refresh();
  }

  return (
    <div>
      <h2>Heartbeat</h2>
      <div className="panel row">
        <button onClick={run}>Run Heartbeat Now</button>
      </div>
      <div className="panel">
        <h4>Latest Result</h4>
        <pre>{JSON.stringify(latest, null, 2)}</pre>
      </div>
      <div className="panel">
        <h4>History</h4>
        {history.map((item, idx) => (
          <pre key={idx}>{JSON.stringify(item, null, 2)}</pre>
        ))}
      </div>
    </div>
  );
}
