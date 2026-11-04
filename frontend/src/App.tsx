import { useEffect, useState } from "react";
import { ApiError, getSummary } from "./api";
import ChatPanel from "./components/ChatPanel";
import SummaryPanel from "./components/SummaryPanel";
import { CloseIcon, LogoIcon, MenuIcon, NewChatIcon } from "./components/icons";
import type { Summary } from "./types";

export type SummaryState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: Summary };

export default function App() {
  const [summary, setSummary] = useState<SummaryState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [chatKey, setChatKey] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showNotice, setShowNotice] = useState(true);

  useEffect(() => {
    let cancelled = false; // Ignores a late response after a retry or unmount.
    setSummary({ status: "loading" });
    getSummary()
      .then((data) => !cancelled && setSummary({ status: "ready", data }))
      .catch((err: ApiError) => !cancelled && setSummary({ status: "error", message: err.message }));
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const data = summary.status === "ready" ? summary.data : null;
  const newChat = () => {
    setChatKey((k) => k + 1); // Remounting the chat clears it.
    setSidebarOpen(false);
  };

  return (
    <div className="app">
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`} aria-label="Sidebar">
        <div className="sidebar-head">
          <span className="brand"><LogoIcon /> Finance Assistant</span>
          <button className="icon-btn close" aria-label="Close sidebar" onClick={() => setSidebarOpen(false)}>
            <CloseIcon />
          </button>
        </div>
        <button className="new-chat" onClick={newChat}><NewChatIcon /> New chat</button>
        <SummaryPanel state={summary} onRetry={() => setAttempt((a) => a + 1)} />
      </aside>
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}

      <main className="main">
        <header className="topbar">
          <button className="icon-btn menu" aria-label="Open sidebar" onClick={() => setSidebarOpen(true)}>
            <MenuIcon />
          </button>
          <span className="title">Procurement Assistant</span>
          {data && (
            <span className={`pill ${data.llm.is_stub ? "warn" : ""}`}>
              {data.llm.is_stub ? "Stub mode" : `${data.llm.provider}${data.llm.model ? ` / ${data.llm.model}` : ""}`}
            </span>
          )}
          <button className="icon-btn topbar-new" aria-label="New chat" onClick={newChat}><NewChatIcon /></button>
        </header>
        {data && (data.llm.is_stub || !data.fx.policy_compliant) && showNotice && (
          <div className="notice" role="status">
            <details>
              <summary>
                {[data.llm.is_stub && "Stub mode: answers use fixed templates",
                  !data.fx.policy_compliant && "EUR figures use indicative FX rates"].filter(Boolean).join(" · ")}
              </summary>
              {data.llm.is_stub && (
                <p>No model is connected. A keyword-based stand-in handles routing, and answers come from fixed
                  templates. Figures are still computed from the data.</p>
              )}
              {!data.fx.policy_compliant && <p>{data.fx.note}</p>}
            </details>
            <button className="icon-btn notice-close" aria-label="Dismiss notice" onClick={() => setShowNotice(false)}>
              <CloseIcon />
            </button>
          </div>
        )}
        <ChatPanel key={chatKey} />
      </main>
    </div>
  );
}
