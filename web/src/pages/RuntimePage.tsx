import { useEffect, useState } from "react";
import { api, makeSse } from "../api";

const names = ["grumpyreachy-run", "slack-bot", "heartbeat", "grumpyreachy-heartbeat"];

export function RuntimePage() {
  const [status, setStatus] = useState<Record<string, any>>({});
  const [events, setEvents] = useState<string[]>([]);

  async function refresh() {
    setStatus((await api.runtimeStatus()) as Record<string, any>);
  }

  useEffect(() => {
    refresh().catch(console.error);
    const stream = makeSse("/runtime/events/stream");
    const push = (e: MessageEvent, label: string) => setEvents((prev) => [`${label}: ${e.data}`, ...prev].slice(0, 80));
    stream.addEventListener("process.started", (e) => push(e as MessageEvent, "started"));
    stream.addEventListener("process.stopped", (e) => push(e as MessageEvent, "stopped"));
    stream.addEventListener("process.exit", (e) => push(e as MessageEvent, "exit"));
    stream.addEventListener("process.log", (e) => push(e as MessageEvent, "log"));
    return () => stream.close();
  }, []);

  async function act(name: string, action: "start" | "stop" | "restart") {
    await api.runtimeAction(name, action);
    await refresh();
  }

  return (
    <div>
      <h2>Runtime</h2>
      <div className="row">
        {names.map((name) => (
          <div className="panel" key={name} style={{ width: 320 }}>
            <h4>{name}</h4>
            <pre>{JSON.stringify(status[name] ?? {}, null, 2)}</pre>
            <div className="row">
              <button onClick={() => act(name, "start")}>Start</button>
              <button onClick={() => act(name, "stop")}>Stop</button>
              <button onClick={() => act(name, "restart")}>Restart</button>
            </div>
          </div>
        ))}
      </div>
      <div className="panel">
        <h4>Live Events</h4>
        {events.map((line, idx) => <div key={idx}>{line}</div>)}
      </div>
    </div>
  );
}
