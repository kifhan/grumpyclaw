import { useEffect, useState } from "react";
import { api, makeSse } from "../api";

export function LogsPage() {
  const [source, setSource] = useState("");
  const [level, setLevel] = useState("");
  const [processName, setProcessName] = useState("");
  const [eventType, setEventType] = useState("");
  const [queryText, setQueryText] = useState("");
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);
  const [live, setLive] = useState<string[]>([]);

  async function refresh() {
    const out = await api.logs({
      source: source || undefined,
      level: level || undefined,
      process_name: processName || undefined,
      event_type: eventType || undefined,
      q: queryText || undefined,
      limit: 200,
    });
    setItems(out.items);
  }

  useEffect(() => {
    refresh().catch(console.error);
  }, [source, level, processName, eventType]);

  useEffect(() => {
    const stream = makeSse("/runtime/events/stream");
    stream.addEventListener("process.log", (e) => setLive((prev) => [String((e as MessageEvent).data), ...prev].slice(0, 100)));
    return () => stream.close();
  }, []);

  return (
    <div>
      <h2>Logs</h2>
      <div className="panel row">
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">all</option>
          <option value="runtime">runtime</option>
          <option value="robot">robot</option>
        </select>
        <select value={level} onChange={(e) => setLevel(e.target.value)}>
          <option value="">all levels</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <input value={processName} onChange={(e) => setProcessName(e.target.value)} placeholder="process_name" />
        <input value={eventType} onChange={(e) => setEventType(e.target.value)} placeholder="event_type" />
        <input value={queryText} onChange={(e) => setQueryText(e.target.value)} placeholder="contains text" />
        <button onClick={() => refresh()}>Refresh</button>
      </div>
      <div className="panel">
        <h4>Stored Logs</h4>
        {items.map((item, idx) => (
          <pre key={idx}>{JSON.stringify(item, null, 2)}</pre>
        ))}
      </div>
      <div className="panel">
        <h4>Live Runtime Tail</h4>
        {live.map((line, idx) => <div key={idx}>{line}</div>)}
      </div>
    </div>
  );
}
