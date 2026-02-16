import { Link, NavLink, Route, Routes } from "react-router-dom";
import { ChatPage } from "./pages/ChatPage";
import { RuntimePage } from "./pages/RuntimePage";
import { RobotPage } from "./pages/RobotPage";
import { MemoryPage } from "./pages/MemoryPage";
import { SkillsPage } from "./pages/SkillsPage";
import { HeartbeatPage } from "./pages/HeartbeatPage";
import { LogsPage } from "./pages/LogsPage";

const links = [
  ["/chat", "Chat"],
  ["/runtime", "Runtime"],
  ["/robot", "Robot"],
  ["/memory", "Memory"],
  ["/skills", "Skills"],
  ["/heartbeat", "Heartbeat"],
  ["/logs", "Logs"],
] as const;

export function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/chat" className="brand">grumpyadmin</Link>
        <p className="warning">Dev mode only: authentication disabled.</p>
      </header>
      <div className="layout">
        <nav className="sidebar">
          {links.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
              {label}
            </NavLink>
          ))}
        </nav>
        <main className="content">
          <Routes>
            <Route path="/" element={<ChatPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/runtime" element={<RuntimePage />} />
            <Route path="/robot" element={<RobotPage />} />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/skills" element={<SkillsPage />} />
            <Route path="/heartbeat" element={<HeartbeatPage />} />
            <Route path="/logs" element={<LogsPage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
