import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import type { KnowledgeItem, Paper, Project } from "../lib/types";
import {
  BookMarked,
  ChevronUp,
  Cpu,
  FolderKanban,
  History,
  Image as ImageIcon,
  Layers,
  LibraryBig,
  LogOut,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  ListChecks,
  Plus,
  Radar,
  ScrollText,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { api } from "../lib/api";
import { cn } from "../lib/utils";
import { USAGE_CHANGED_EVENT } from "../lib/events";
import { Avatar, IconButton, Input, Modal } from "./ui";
import { Onboarding } from "./Onboarding";
import { UploadResultNotice } from "./Uploader";

const NAV = [
  { to: "/app", label: "AI 研究助手", icon: Sparkles, end: true },
  { to: "/app/intelligence", label: "研究情报", icon: Radar },
  { to: "/app/tasks", label: "任务中心", icon: ListChecks },
  { to: "/app/artifacts", label: "学术成果", icon: ScrollText },
  { to: "/app/papers", label: "论文阅读", icon: LibraryBig },
  { to: "/app/research", label: "多论文研究", icon: Layers },
  { to: "/app/knowledge", label: "个人知识库", icon: BookMarked },
  { to: "/app/evidence", label: "证据库", icon: ShieldCheck },
  { to: "/app/figures", label: "图片与图表", icon: ImageIcon },
  { to: "/app/projects", label: "研究项目", icon: FolderKanban },
  { to: "/app/history", label: "历史记录", icon: History },
  { to: "/app/settings", label: "设置", icon: Settings2 },
];

const TITLES: Record<string, string> = {
  "/app": "AI 研究助手",
  "/app/intelligence": "研究情报",
  "/app/tasks": "任务中心",
  "/app/artifacts": "学术成果",
  "/app/papers": "论文阅读",
  "/app/research": "多论文研究",
  "/app/knowledge": "个人知识库",
  "/app/evidence": "证据库",
  "/app/figures": "图片与图表",
  "/app/projects": "研究项目",
  "/app/history": "历史记录",
  "/app/settings": "设置中心",
};

export function Shell() {
  const { user, settings, model, logout, setTheme } = useApp();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userMenu, setUserMenu] = useState(false);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("paperlens.sidebar") === "collapsed");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<{ papers: Paper[]; knowledge: KnowledgeItem[]; projects: Project[] }>({
    papers: [], knowledge: [], projects: [],
  });
  const [usage, setUsage] = useState<{ papers: number; pages: number; conversations?: number } | null>(null);
  const usageSeq = useRef(0);
  const usageAbort = useRef<AbortController | null>(null);
  const location = useLocation();
  const navigate = useNavigate();

  const loadUsage = useCallback(() => {
    const seq = ++usageSeq.current;
    usageAbort.current?.abort();
    const controller = new AbortController();
    usageAbort.current = controller;
    api<{ papers: number; pages: number }>("/settings/usage", { signal: controller.signal })
      .then((data) => {
        if (seq === usageSeq.current) setUsage(data);
      })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        if (seq === usageSeq.current) setUsage(null);
      });
  }, []);

  useEffect(() => {
    setMobileOpen(false);
    setUserMenu(false);
  }, [location.pathname]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
        return;
      }
      if (!typing && !event.metaKey && !event.ctrlKey && !event.altKey && event.key.toLowerCase() === "n") {
        event.preventDefault();
        navigate("/app?new=1");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  useEffect(() => {
    if (!searchOpen || !searchQuery.trim()) {
      setSearchResults({ papers: [], knowledge: [], projects: [] });
      setSearching(false);
      return;
    }
    let active = true;
    const timer = window.setTimeout(() => {
      setSearching(true);
      const needle = searchQuery.trim();
      Promise.all([
        api<{ items: Paper[] }>("/papers?limit=6&query=" + encodeURIComponent(needle)),
        api<{ items: KnowledgeItem[] }>("/knowledge?limit=6&query=" + encodeURIComponent(needle)),
        api<{ items: Project[] }>("/projects"),
      ])
        .then(([paperResponse, knowledgeResponse, projectResponse]) => {
          if (!active) return;
          const lowered = needle.toLowerCase();
          setSearchResults({
            papers: paperResponse.items,
            knowledge: knowledgeResponse.items,
            projects: projectResponse.items.filter((project) =>
              (project.name + " " + (project.description || "") + " " + (project.goal || "")).toLowerCase().includes(lowered),
            ).slice(0, 6),
          });
        })
        .catch(() => {
          if (active) setSearchResults({ papers: [], knowledge: [], projects: [] });
        })
        .finally(() => {
          if (active) setSearching(false);
        });
    }, 260);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [searchOpen, searchQuery]);

  useEffect(() => {
    loadUsage();
  }, [location.pathname, loadUsage]);

  useEffect(() => {
    let timer: number | undefined;
    const onUsageChanged = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(loadUsage, 120);
    };
    window.addEventListener(USAGE_CHANGED_EVENT, onUsageChanged);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener(USAGE_CHANGED_EVENT, onUsageChanged);
    };
  }, [loadUsage]);

  useEffect(() => () => usageAbort.current?.abort(), []);

  const title =
    TITLES[location.pathname] ||
    (location.pathname.startsWith("/app/papers/") ? "论文精读" : location.pathname.startsWith("/app/projects/") ? "研究项目" : "PaperLens");
  const dark = document.documentElement.dataset.theme === "dark";

  function toggleSidebar() {
    setCollapsed((current) => {
      const next = !current;
      localStorage.setItem("paperlens.sidebar", next ? "collapsed" : "expanded");
      return next;
    });
  }

  return (
    <div className={cn("app-shell", collapsed && "sidebar-collapsed")}>
      <aside className={cn("sidebar", mobileOpen && "sidebar-open")}>
        <div className="sidebar-top">
          <NavLink to="/app" className="brand">
            <BrandMark />
            <span>
              <strong>PaperLens</strong>
              <small>知研 AI</small>
            </span>
          </NavLink>
          <IconButton
            label={collapsed ? "展开导航" : "收起导航"}
            className="sidebar-collapse"
            onClick={toggleSidebar}
          >
            {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </IconButton>
          <IconButton label="关闭导航" className="sidebar-close" onClick={() => setMobileOpen(false)}>
            <X size={18} />
          </IconButton>
        </div>

        <button className="new-research" onClick={() => navigate("/app?new=1")}>
          <Plus size={16} />
          <span>新建研究</span>
          <kbd>N</kbd>
        </button>

        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => cn("nav-item", isActive && "nav-active")}
              title={item.label}
            >
              <item.icon size={17} strokeWidth={1.8} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="usage-card">
            <div className="usage-head">
              <span>研究空间</span>
              <span className="usage-plan">{user?.plan === "researcher" ? "Researcher" : user?.plan}</span>
            </div>
            <div className="usage-stats">
              <div>
                <strong>{usage?.papers ?? 0}</strong>
                <span>论文</span>
              </div>
              <div>
                <strong>{usage?.pages ?? 0}</strong>
                <span>页解析</span>
              </div>
            </div>
            <div className="usage-model">
              <Cpu size={13} />
              {model?.configured ? "DeepSeek · " + model.model : "本地抽取模式"}
            </div>
          </div>

          <div className="user-block">
            <button className="user-row" onClick={() => setUserMenu((open) => !open)}>
              <Avatar name={user?.display_name || "PL"} color={user?.avatar_color} size={34} />
              <span className="user-meta">
                <strong>{user?.display_name}</strong>
                <small>{user?.affiliation || user?.email}</small>
              </span>
              <ChevronUp size={15} className={cn("rotate-180", userMenu && "rotate-0")} />
            </button>
            {userMenu && (
              <div className="user-menu">
                <button onClick={() => navigate("/app/settings")}>
                  <Settings2 size={15} /> 账号与设置
                </button>
                <button onClick={() => setTheme(dark ? "light" : "dark")}>
                  {dark ? <Sun size={15} /> : <Moon size={15} />} {dark ? "浅色主题" : "深色主题"}
                </button>
                <button
                  className="danger-text"
                  onClick={() => {
                    logout();
                    navigate("/");
                  }}
                >
                  <LogOut size={15} /> 退出登录
                </button>
              </div>
            )}
          </div>
        </div>
      </aside>

      {mobileOpen && <div className="sidebar-scrim" onClick={() => setMobileOpen(false)} />}

      <div className="app-body">
        <header className="topbar">
          <div className="topbar-left">
            <IconButton label="打开导航" className="menu-btn" onClick={() => setMobileOpen(true)}>
              <Menu size={19} />
            </IconButton>
            <div className="breadcrumb">
              <span className="crumb-root">PaperLens</span>
              <span className="crumb-sep">/</span>
              <span className="crumb-current">{title}</span>
            </div>
          </div>
          <div className="topbar-right">
            <button className="search-trigger" onClick={() => setSearchOpen(true)}>
              <Search size={15} />
              <span>搜索论文、知识、项目</span>
              <kbd>⌘K</kbd>
            </button>
            <span className={cn("model-pill", model?.configured ? "model-live" : "model-local")}>
              <span className="dot" />
              {model?.configured ? model.model : "本地抽取"}
            </span>
            <IconButton label={dark ? "切换到浅色" : "切换到深色"} onClick={() => setTheme(dark ? "light" : "dark")}>
              {dark ? <Sun size={17} /> : <Moon size={17} />}
            </IconButton>
          </div>
        </header>

        <main className="app-main">
          <Outlet />
        </main>
      </div>

      <Modal
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        title="全局搜索"
        subtitle="论文、个人知识、研究项目"
        size="lg"
        footer={<span className="muted small">Enter 打开 · Esc 关闭</span>}
      >
        <div className="command-search">
          <Input
            autoFocus
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== "Enter") return;
              const paper = searchResults.papers[0];
              const knowledge = searchResults.knowledge[0];
              const project = searchResults.projects[0];
              if (paper) {
                setSearchOpen(false);
                navigate("/app/papers/" + paper.id);
              } else if (knowledge) {
                setSearchOpen(false);
                navigate("/app/knowledge");
              } else if (project) {
                setSearchOpen(false);
                navigate("/app/projects");
              }
            }}
            placeholder="输入论文标题、知识内容或项目名称…"
          />
          {searching && <p className="muted small">搜索中…</p>}
          {!searching && searchQuery.trim() && (
            <div className="command-results">
              {searchResults.papers.length > 0 && (
                <div className="command-group">
                  <span className="command-label">论文</span>
                  {searchResults.papers.map((paper) => (
                    <button key={paper.id} onClick={() => { setSearchOpen(false); navigate("/app/papers/" + paper.id); }}>
                      <BookMarked size={14} />
                      <span>{paper.title}</span>
                      <em>{paper.year || "n.d."}</em>
                    </button>
                  ))}
                </div>
              )}
              {searchResults.knowledge.length > 0 && (
                <div className="command-group">
                  <span className="command-label">知识</span>
                  {searchResults.knowledge.map((item) => (
                    <button key={item.id} onClick={() => { setSearchOpen(false); navigate("/app/knowledge"); }}>
                      <BookMarked size={14} />
                      <span>{item.title}</span>
                      <em>{item.kind}</em>
                    </button>
                  ))}
                </div>
              )}
              {searchResults.projects.length > 0 && (
                <div className="command-group">
                  <span className="command-label">项目</span>
                  {searchResults.projects.map((project) => (
                    <button key={project.id} onClick={() => { setSearchOpen(false); navigate("/app/projects"); }}>
                      <FolderKanban size={14} />
                      <span>{project.name}</span>
                      <em>{project.progress}%</em>
                    </button>
                  ))}
                </div>
              )}
              {searchResults.papers.length + searchResults.knowledge.length + searchResults.projects.length === 0 && (
                <p className="muted small">没有匹配结果。</p>
              )}
            </div>
          )}
        </div>
      </Modal>

      <UploadResultNotice />

      {settings && !settings.onboarding_completed && <Onboarding />}
    </div>
  );
}

function BrandMark() {
  return (
    <svg width="34" height="34" viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="15" fill="currentColor" className="brand-bg" />
      <circle cx="28" cy="28" r="13" fill="none" stroke="#ECE7D9" strokeWidth="4" />
      <path d="M38 38 L50 50" stroke="#C8A96A" strokeWidth="5" strokeLinecap="round" />
      <path d="M20 30c5-8 11-8 16 0" stroke="#ECE7D9" strokeWidth="3" fill="none" strokeLinecap="round" />
    </svg>
  );
}