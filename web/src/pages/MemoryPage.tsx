import { FormEvent, useState } from "react";
import { api } from "../api";

export function MemoryPage() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Array<any>>([]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setHits((await api.searchMemory(q, 8)) as Array<any>);
  }

  return (
    <div>
      <h2>Memory Search</h2>
      <form onSubmit={submit} className="panel row">
        <input value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1 }} placeholder="Search memory..." />
        <button type="submit">Search</button>
      </form>
      {hits.map((h, idx) => (
        <div key={idx} className="panel">
          <b>{h.title}</b> (score {Number(h.score).toFixed(3)})
          <p>{h.content}</p>
        </div>
      ))}
    </div>
  );
}
