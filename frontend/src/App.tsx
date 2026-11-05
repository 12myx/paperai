import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useApp } from "./store/AppContext";
import { Shell } from "./components/Shell";
import { Toasts, Spinner } from "./components/ui";
import { Landing } from "./pages/Landing";
import { Auth } from "./pages/Auth";
import { Home } from "./pages/Home";
import { Library } from "./pages/Library";
import { Reader } from "./pages/Reader";
import { Research } from "./pages/Research";
import { Intelligence } from "./pages/Intelligence";
import { Tasks } from "./pages/Tasks";
import { Artifacts } from "./pages/Artifacts";
import { Knowledge } from "./pages/Knowledge";
import { Figures } from "./pages/Figures";
import { Projects } from "./pages/Projects";
import { History } from "./pages/History";
import { Settings } from "./pages/Settings";
import { EvidenceLibrary } from "./pages/Evidence";
import { EvidenceProvider } from "./store/EvidenceContext";

function Protected({ children }: { children: ReactNode }) {
  const { ready, authed } = useApp();
  if (!ready) {
    return (
      <div className="app-splash">
        <div className="app-splash-mark">
          <svg width="46" height="46" viewBox="0 0 64 64" aria-hidden="true">
            <rect width="64" height="64" rx="15" fill="#1F3B34" />
            <circle cx="28" cy="28" r="13" fill="none" stroke="#ECE7D9" strokeWidth="4" />
            <path d="M38 38 L50 50" stroke="#C8A96A" strokeWidth="5" strokeLinecap="round" />
          </svg>
        </div>
        <Spinner size={20} />
        <span>正在打开你的研究空间…</span>
      </div>
    );
  }
  if (!authed) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function NotFound() {
  return (
    <div className="app-splash">
      <h1 style={{ fontSize: 40 }}>404</h1>
      <p className="muted">这个页面不存在，或者已经被移动。</p>
      <a className="btn btn-primary btn-md" href="/app">回到研究空间</a>
    </div>
  );
}

export default function App() {
  return (
    <>
      <EvidenceProvider>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Auth mode="login" />} />
        <Route path="/register" element={<Auth mode="register" />} />
        <Route
          element={
            <Protected>
              <Shell />
            </Protected>
          }
        >
          <Route path="/app" element={<Home />} />
          <Route path="/app/papers" element={<Library />} />
          <Route path="/app/papers/:paperId" element={<Reader />} />
          <Route path="/app/research" element={<Research />} />
          <Route path="/app/intelligence" element={<Intelligence />} />
          <Route path="/app/tasks" element={<Tasks />} />
          <Route path="/app/artifacts" element={<Artifacts />} />
          <Route path="/app/knowledge" element={<Knowledge />} />
          <Route path="/app/evidence" element={<EvidenceLibrary />} />
          <Route path="/app/figures" element={<Figures />} />
          <Route path="/app/projects" element={<Projects />} />
          <Route path="/app/history" element={<History />} />
          <Route path="/app/settings" element={<Settings />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
      </EvidenceProvider>
      <Toasts />
    </>
  );
}