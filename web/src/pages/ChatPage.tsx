import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, makeSse, type ChatMode } from "../api";

type Session = { id: string; mode: ChatMode; title: string };
type Msg = { id: string; role: string; content: string; status: string };

export function ChatPage() {
  const [mode, setMode] = useState<ChatMode>("grumpyclaw");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [events, setEvents] = useState<string[]>([]);

  const selectedSession = useMemo(() => sessions.find((s) => s.id === selected), [sessions, selected]);

  async function refreshSessions() {
    const out = await api.listSessions();
    setSessions(out as Session[]);
    if (!selected && out.length > 0) setSelected(out[0].id);
  }

  async function refreshMessages(id: string) {
    const out = await api.listMessages(id);
    setMessages(out as Msg[]);
  }

  useEffect(() => {
    refreshSessions().catch(console.error);
  }, []);

  useEffect(() => {
    if (!selected) return;
    refreshMessages(selected).catch(console.error);
    const stream = makeSse(`/chat/sessions/${selected}/stream`);
    stream.addEventListener("chat.token", (e) => {
      const payload = JSON.parse((e as MessageEvent).data) as { message_id: string; token: string };
      setMessages((prev) => prev.map((m) => (m.id === payload.message_id ? { ...m, content: `${m.content}${payload.token}` } : m)));
    });
    stream.addEventListener("chat.final", (e) => {
      const payload = JSON.parse((e as MessageEvent).data) as { message_id: string; content: string };
      setMessages((prev) => prev.map((m) => (m.id === payload.message_id ? { ...m, content: payload.content, status: "final" } : m)));
    });
    stream.addEventListener("tool.event", (e) => {
      const payload = JSON.parse((e as MessageEvent).data) as { tool_name: string; phase: string; message: string };
      setEvents((prev) => [`${payload.phase} ${payload.tool_name}: ${payload.message}`, ...prev].slice(0, 30));
    });
    stream.addEventListener("robot.feedback", (e) => {
      const payload = JSON.parse((e as MessageEvent).data) as { state: string; message: string };
      setEvents((prev) => [`robot ${payload.state}: ${payload.message}`, ...prev].slice(0, 30));
    });
    return () => stream.close();
  }, [selected]);

  async function createSession() {
    const created = await api.createSession(mode);
    await refreshSessions();
    setSelected(created.session_id);
  }

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    if (!selected || !text.trim()) return;
    await api.postMessage(selected, text.trim());
    setText("");
    await refreshMessages(selected);
  }

  return (
    <div>
      <h2>Chat</h2>
      <div className="panel row">
        <select value={mode} onChange={(e) => setMode(e.target.value as ChatMode)}>
          <option value="grumpyclaw">grumpyclaw</option>
          <option value="grumpyreachy">grumpyreachy</option>
        </select>
        <button onClick={createSession}>New Session</button>
      </div>
      <div className="row">
        <div className="panel" style={{ width: 300 }}>
          <h4>Sessions</h4>
          {sessions.map((s) => (
            <button key={s.id} onClick={() => setSelected(s.id)} style={{ width: "100%", marginBottom: 6 }}>
              {s.mode} | {s.title}
            </button>
          ))}
        </div>
        <div className="panel" style={{ flex: 1 }}>
          <h4>Conversation {selectedSession ? `(${selectedSession.mode})` : ""}</h4>
          {messages.map((m) => (
            <pre key={m.id}><b>{m.role}</b>: {m.content || "..."}</pre>
          ))}
          <form onSubmit={onSubmit} className="row">
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a message" style={{ flex: 1 }} />
            <button type="submit">Send</button>
          </form>
        </div>
      </div>
      <div className="panel">
        <h4>Tool / Robot Timeline</h4>
        {events.map((line, idx) => <div key={idx}>{line}</div>)}
      </div>
    </div>
  );
}
