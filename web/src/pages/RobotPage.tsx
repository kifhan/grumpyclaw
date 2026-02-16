import { useState } from "react";
import { api } from "../api";

export function RobotPage() {
  const [result, setResult] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [look, setLook] = useState({ x: 0.35, y: 0, z: 0.1, duration: 1 });
  const [state, setState] = useState("attention");
  const [text, setText] = useState("Hello from grumpyadmin");

  async function run(payload: Record<string, unknown>) {
    const out = await api.robotAction(payload);
    setResult(JSON.stringify(out, null, 2));
  }

  return (
    <div>
      <h2>Robot Control</h2>
      <div className="panel row">
        <label><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} /> Confirm risky actions</label>
      </div>

      <div className="panel">
        <h4>Gestures</h4>
        <div className="row">
          <button onClick={() => run({ action: "nod" })}>Nod</button>
          <select value={state} onChange={(e) => setState(e.target.value)}>
            <option>attention</option>
            <option>success</option>
            <option>error</option>
            <option>neutral</option>
          </select>
          <button onClick={() => run({ action: "antenna_feedback", state })}>Antenna</button>
        </div>
      </div>

      <div className="panel">
        <h4>Look At</h4>
        <div className="row">
          <input type="number" value={look.x} onChange={(e) => setLook({ ...look, x: Number(e.target.value) })} />
          <input type="number" value={look.y} onChange={(e) => setLook({ ...look, y: Number(e.target.value) })} />
          <input type="number" value={look.z} onChange={(e) => setLook({ ...look, z: Number(e.target.value) })} />
          <input type="number" value={look.duration} onChange={(e) => setLook({ ...look, duration: Number(e.target.value) })} />
          <button onClick={() => run({ action: "look_at", ...look, confirm })}>Send Look</button>
        </div>
      </div>

      <div className="panel">
        <h4>Speak</h4>
        <div className="row">
          <input value={text} onChange={(e) => setText(e.target.value)} style={{ flex: 1 }} />
          <button onClick={() => run({ action: "speak", text, confirm })}>Speak</button>
        </div>
      </div>
      <pre>{result}</pre>
    </div>
  );
}
