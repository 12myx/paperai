import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, BookMarked, Quote, ShieldCheck } from "lucide-react";
import { useApp } from "../store/AppContext";
import { api } from "../lib/api";
import { Button, Field, Input } from "../components/ui";
import type { Settings, User } from "../lib/types";

export function Auth({ mode }: { mode: "login" | "register" }) {
  const { login, toast } = useApp();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isRegister = mode === "register";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!email.includes("@")) {
      setError("请输入有效的邮箱地址");
      return;
    }
    if (password.length < 8) {
      setError("密码至少需要 8 位");
      return;
    }
    setLoading(true);
    try {
      const path = isRegister ? "/auth/register" : "/auth/login";
      const response = await api<{ access_token: string; user: User; settings: Settings }>(path, {
        method: "POST",
        body: isRegister
          ? { email: email.trim(), password, display_name: displayName.trim() }
          : { email: email.trim(), password },
      });
      await login(response.access_token, response.user, response.settings);
      toast(isRegister ? "欢迎加入 PaperLens" : "欢迎回来", "success");
      navigate("/app");
    } catch (requestError) {
      setError((requestError as Error).message || "操作失败，请重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <aside className="auth-aside">
        <div className="auth-top">
          <Link to="/" className="auth-brand">
            <svg width="30" height="30" viewBox="0 0 64 64" aria-hidden="true">
              <rect width="64" height="64" rx="15" fill="#1F3B34" />
              <circle cx="28" cy="28" r="13" fill="none" stroke="#ECE7D9" strokeWidth="4" />
              <path d="M38 38 L50 50" stroke="#C8A96A" strokeWidth="5" strokeLinecap="round" />
            </svg>
            <span>PaperLens <small>知研</small></span>
          </Link>
          <Link to="/" className="auth-back">
            <ArrowLeft size={14} /> 返回首页
          </Link>
        </div>
        <div className="auth-aside-body">
          <span className="eyebrow">PaperLens AI</span>
          <h1>和论文建立一种<br />可以积累的关系。</h1>
          <p>不是又一个聊天窗口。PaperLens 把阅读、提问、核验与知识沉淀放在同一条研究链路里。</p>
          <ul>
            <li><Quote size={16} /> 回答带页码与原文引用</li>
            <li><ShieldCheck size={16} /> 论文私有，账号间完全隔离</li>
            <li><BookMarked size={16} /> 结论可保存、可导出、可关联</li>
          </ul>
        </div>
        <div className="auth-quote">
          <p>“科研不是读得更多，而是把读过的留下来。”</p>
          <span>PaperLens 设计原则</span>
        </div>
      </aside>

      <main className="auth-main">
        <div className="auth-card">
          <header>
            <h2>{isRegister ? "创建你的研究空间" : "继续你的研究"}</h2>
            <p>{isRegister ? "几秒钟即可开始，第一周足够读完三篇论文。" : "登录后回到你的论文、知识与项目。"}</p>
          </header>
          <form onSubmit={submit}>
            {isRegister && (
              <Field label="你的称呼">
                <Input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="例如：林同学" autoComplete="name" />
              </Field>
            )}
            <Field label="邮箱">
              <Input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@university.edu"
                autoComplete="email"
                required
              />
            </Field>
            <Field label="密码" hint={isRegister ? "至少 8 位，建议使用密码管理器生成的强密码" : undefined}>
              <Input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="••••••••"
                autoComplete={isRegister ? "new-password" : "current-password"}
                required
              />
            </Field>
            {error && <div className="form-error">{error}</div>}
            <Button type="submit" variant="primary" size="lg" loading={loading} className="auth-submit">
              {isRegister ? "创建账号" : "登录"} <ArrowRight size={16} />
            </Button>
          </form>
          <p className="auth-switch">
            {isRegister ? "已经有账号？" : "还没有账号？"}
            <Link to={isRegister ? "/login" : "/register"}>{isRegister ? "直接登录" : "免费创建"}</Link>
          </p>
          <div className="auth-note">
            <span className="dot" />
            未配置模型时使用本地抽取模式，回答仍基于真实论文片段，但不会生成式改写或翻译。
          </div>
        </div>
      </main>
    </div>
  );
}