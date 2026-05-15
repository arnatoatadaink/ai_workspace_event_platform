import { useEffect, useState } from "react";
import { fetchSessions, type SessionInfo } from "./api";
import { ChatPane } from "./ChatPane";
import { DetailSidebar } from "./DetailSidebar";
import { HomePage } from "./HomePage";
import { DataFlowPage } from "./pages/DataFlowPage";
import SettingsPage from "./pages/SettingsPage";
import { TopicGraphPage } from "./pages/TopicGraphPage";
import { SessionList } from "./SessionList";
import { UmapPage } from "./UmapPage";
import "./app.css";

type Page = "home" | "events" | "umap" | "topic-graph" | "dataflow" | "settings";

const LS_LAST_SESSION = "awep:lastSession";
const LS_SIDEBAR_OPEN = "awep:sidebarOpen";

export function App() {
  const [page, setPage] = useState<Page>("home");
  const [selectedSession, setSelectedSession] = useState<string | null>(
    () => localStorage.getItem(LS_LAST_SESSION),
  );
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(
    () => localStorage.getItem(LS_SIDEBAR_OPEN) !== "false",
  );
  const [sessions, setSessions] = useState<SessionInfo[]>([]);

  useEffect(() => {
    fetchSessions().then(setSessions).catch(console.error);
  }, []);

  function refreshSessions() {
    fetchSessions().then(setSessions).catch(console.error);
  }

  function selectSession(id: string) {
    setSelectedSession(id);
    localStorage.setItem(LS_LAST_SESSION, id);
  }

  function openSession(id: string) {
    selectSession(id);
    setPage("events");
  }

  function toggleSidebar() {
    setSidebarOpen((prev) => {
      const next = !prev;
      localStorage.setItem(LS_SIDEBAR_OPEN, String(next));
      return next;
    });
  }

  return (
    <div className="layout">
      <header className="app-header">
        <nav className="app-nav">
          <button
            className={`nav-btn${page === "home" ? " active" : ""}`}
            onClick={() => setPage("home")}
          >
            ホーム
          </button>
          <button
            className={`nav-btn${page === "events" ? " active" : ""}`}
            onClick={() => setPage("events")}
          >
            イベントビュー
          </button>
          <button
            className={`nav-btn${page === "umap" ? " active" : ""}`}
            onClick={() => setPage("umap")}
          >
            トピックマップ
          </button>
          <button
            className={`nav-btn${page === "topic-graph" ? " active" : ""}`}
            onClick={() => setPage("topic-graph")}
          >
            トピックグラフ
          </button>
          <button
            className={`nav-btn${page === "dataflow" ? " active" : ""}`}
            onClick={() => setPage("dataflow")}
          >
            データフロー
          </button>
          <button
            className={`nav-btn${page === "settings" ? " active" : ""}`}
            onClick={() => setPage("settings")}
          >
            設定
          </button>
        </nav>
        <span className="app-title">AI Workspace Event Platform</span>
      </header>

      {page === "home" && (
        <main className="home-wrapper">
          <HomePage
            onOpenSession={openSession}
            sessions={sessions}
            onSessionsRefresh={refreshSessions}
          />
        </main>
      )}

      {page === "umap" && (
        <main className="home-wrapper">
          <UmapPage />
        </main>
      )}

      {page === "topic-graph" && (
        <main className="topic-graph-wrapper">
          <TopicGraphPage />
        </main>
      )}

      {page === "dataflow" && (
        <main className="dataflow-wrapper">
          <DataFlowPage />
        </main>
      )}

      {page === "settings" && (
        <main className="home-wrapper">
          <SettingsPage />
        </main>
      )}

      {page === "events" && (
        <div className="events-layout">
          <aside className="events-left">
            <SessionList selectedId={selectedSession} onSelect={selectSession} />
          </aside>
          <main className="events-main">
            <ChatPane
              sessionId={selectedSession}
              onToggleSidebar={toggleSidebar}
              sidebarOpen={sidebarOpen}
            />
          </main>
          {sidebarOpen && (
            <DetailSidebar sessionId={selectedSession} onClose={toggleSidebar} />
          )}
        </div>
      )}
    </div>
  );
}
