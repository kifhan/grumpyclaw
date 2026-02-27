import { useEffect, useState } from "react";
import { api, makeSse } from "../api";

type RobotStatus = {
  run_state: string;
  robot_connected: boolean;
  thread_alive: boolean;
  ts?: string;
};

export function RuntimePage() {
  const [status, setStatus] = useState<Record<string, unknown>>({});
  const [robotStatus, setRobotStatus] = useState<RobotStatus | null>(null);
  const [events, setEvents] = useState<string[]>([]);

  async function refresh() {
    setStatus((await api.runtimeStatus()) as Record<string, unknown>);
    setRobotStatus(await api.robotStatus());
  }

  useEffect(() => {
    refresh().catch(console.error);
    const stream = makeSse("/runtime/events/stream");
    stream.addEventListener("runtime.heartbeat", (e) => {
      const payload = (e as MessageEvent).data;
      setEvents((prev) => [`runtime.heartbeat: ${payload}`, ...prev].slice(0, 80));
      refresh().catch(console.error);
    });
    return () => stream.close();
  }, []);

  async function heartbeatAct(action: "start" | "stop" | "run-now") {
    if (action === "start") await api.runtimeHeartbeatStart();
    else if (action === "stop") await api.runtimeHeartbeatStop();
    else await api.runtimeHeartbeatRunNow();
    await refresh();
  }

  async function robotAct(action: "start" | "stop" | "restart") {
    if (action === "start") await api.robotStart();
    else if (action === "stop") await api.robotStop();
    else await api.robotRestart();
    await refresh();
  }

  return (
    <div>
      <h2>Runtime</h2>
      <div className="row">
        <div className="panel" style={{ width: 340 }}>
          <h4>Heartbeat scheduler (in-process)</h4>
          <pre>{JSON.stringify((status["heartbeat"] ?? {}) as Record<string, unknown>, null, 2)}</pre>
          <div className="row">
            <button onClick={() => heartbeatAct("start")}>Start</button>
            <button onClick={() => heartbeatAct("stop")}>Stop</button>
            <button onClick={() => heartbeatAct("run-now")}>Run Now</button>
          </div>
        </div>

        <div className="panel" style={{ width: 340 }}>
          <h4>Realtime service (server-side)</h4>
          <pre>{JSON.stringify((status["realtime"] ?? {}) as Record<string, unknown>, null, 2)}</pre>
        </div>

        <div className="panel" style={{ width: 340 }}>
          <h4>Robot service (in-process)</h4>
          <pre>{robotStatus ? JSON.stringify(robotStatus, null, 2) : "—"}</pre>
          <div className="row">
            <button onClick={() => robotAct("start")}>Start</button>
            <button onClick={() => robotAct("stop")}>Stop</button>
            <button onClick={() => robotAct("restart")}>Restart</button>
          </div>
        </div>
      </div>

      <div className="panel">
        <h4>Live Runtime Events</h4>
        {events.map((line, idx) => <div key={idx}>{line}</div>)}
      </div>
    </div>
  );
}
