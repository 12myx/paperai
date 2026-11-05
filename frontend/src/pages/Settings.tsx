import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  Cpu,
  Database,
  Download,
  Eye,
  FileText,
  Info,
  KeyRound,
  Languages,
  BookOpen,
  Palette,
  Settings2,
  Shield,
  SlidersHorizontal,
  Trash2,
  UserRound,
} from "lucide-react";
import { useApp } from "../store/AppContext";
import { api, downloadFile, setToken } from "../lib/api";
import type { ExportRecord, ModelStatus } from "../lib/types";
import { cn, formatBytes, formatDate, SUMMARY_MODES } from "../lib/utils";
import { Badge, Button, Card, ConfirmDialog, Field, Input, Modal, Select, Spinner } from "../components/ui";

const SECTIONS = [
  { id: "profile", label: "个人资料", icon: UserRound },
  { id: "model", label: "AI 模型配置", icon: Cpu },
  { id: "params", label: "模型参数", icon: SlidersHorizontal },
  { id: "reading", label: "阅读偏好", icon: BookOpen },
  { id: "language", label: "语言与翻译", icon: Languages },
  { id: "appearance", label: "主题设置", icon: Palette },
  { id: "data", label: "数据管理", icon: Database },
  { id: "api", label: "API 配置", icon: KeyRound },
  { id: "privacy", label: "隐私与安全", icon: Shield },
  { id: "about", label: "关于知研", icon: Info },
];

export function Settings() {
  const { user, settings, model, updateSettings, setTheme, setModel, logout, toast, refresh } = useApp();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [section, setSection] = useState(searchParams.get("section") || "profile");

  useEffect(() => {
    const requested = searchParams.get("section");
    if (requested) setSection(requested);
  }, [searchParams]);

  function go(id: string) {
    setSection(id);
    setSearchParams({ section: id }, { replace: true });
  }

  if (!user || !settings) {
    return <div className="page settings-loading"><Spinner size={22} /></div>;
  }

  return (
    <div className="page page-settings">
      <header className="page-head">
        <div>
          <span className="eyebrow">Settings</span>
          <h1>设置中心</h1>
          <p>模型、阅读偏好与数据控制都集中在这里。API Key 只保存在服务端并加密存储。</p>
        </div>
        <Badge tone={model?.configured ? "accent" : "warn"}>{model?.configured ? "生成式模式" : "本地抽取模式"}</Badge>
      </header>

      <div className="settings-layout">
        <nav className="settings-nav">
          {SECTIONS.map((item) => (
            <button key={item.id} className={cn(section === item.id && "active")} onClick={() => go(item.id)}>
              <item.icon size={16} />
              {item.label}
            </button>
          ))}
        </nav>

        <div className="settings-content">
          {section === "profile" && <ProfileSection />}
          {section === "model" && <ModelSection onModel={setModel} />}
          {section === "params" && <ParamsSection />}
          {section === "reading" && <ReadingSection />}
          {section === "language" && <LanguageSection />}
          {section === "appearance" && <AppearanceSection />}
          {section === "data" && <DataSection />}
          {section === "api" && <ApiSection />}
          {section === "privacy" && <PrivacySection />}
          {section === "about" && <AboutSection />}
        </div>
      </div>

      <div className="settings-foot-note">
        <Settings2 size={13} /> PaperLens AI · 你的研究资料不会被用于训练第三方模型。密钥仅用于转发你的模型请求。
      </div>
    </div>
  );

  function ProfileSection() {
    const [name, setName] = useState(user!.display_name);
    const [affiliation, setAffiliation] = useState(user!.affiliation || "");
    const [color, setColor] = useState(user!.avatar_color);
    const [saving, setSaving] = useState(false);
    const [passwordOpen, setPasswordOpen] = useState(false);
    const [current, setCurrent] = useState("");
    const [next, setNext] = useState("");
    const [changing, setChanging] = useState(false);

    async function save() {
      setSaving(true);
      try {
        await api("/auth/profile", { method: "PATCH", body: { display_name: name, affiliation, avatar_color: color } });
        await refresh();
        toast("个人资料已更新", "success");
      } catch {
        toast("保存失败", "error");
      } finally {
        setSaving(false);
      }
    }

    async function changePassword() {
      if (next.length < 8) {
        toast("新密码至少 8 位", "error");
        return;
      }
      setChanging(true);
      try {
        await api("/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } });
        setPasswordOpen(false);
        setCurrent("");
        setNext("");
        toast("密码已更新", "success");
      } catch (error) {
        toast((error as Error).message || "更新失败", "error");
      } finally {
        setChanging(false);
      }
    }

    return (
      <>
        <SectionCard title="个人资料" description="这些信息只用于界面显示，不会公开。">
          <div className="profile-row">
            <span className="profile-avatar" style={{ background: color }}>{name.slice(0, 2).toUpperCase()}</span>
            <div>
              <strong>{user!.email}</strong>
              <span className="muted small">注册于 {formatDate(user!.created_at)} · 方案：{user!.plan}</span>
            </div>
          </div>
          <div className="form-grid">
            <Field label="显示名称">
              <Input value={name} onChange={(event) => setName(event.target.value)} />
            </Field>
            <Field label="学校 / 机构">
              <Input value={affiliation} onChange={(event) => setAffiliation(event.target.value)} placeholder="例如：XX 大学 计算机学院" />
            </Field>
          </div>
          <Field label="头像颜色">
            <div className="color-choices">
              {["#2F6F62", "#3E6591", "#9B6B3F", "#7B5EA7", "#A6463B", "#4A5560"].map((option) => (
                <button
                  key={option}
                  className={cn("color-choice", color === option && "active")}
                  style={{ background: option }}
                  onClick={() => setColor(option)}
                  aria-label={option}
                />
              ))}
            </div>
          </Field>
          <div className="section-actions">
            <Button variant="primary" loading={saving} onClick={() => void save()}>保存资料</Button>
            <Button variant="ghost" onClick={() => setPasswordOpen(true)}>修改密码</Button>
          </div>
        </SectionCard>

        <Modal
          open={passwordOpen}
          onClose={() => setPasswordOpen(false)}
          title="修改密码"
          size="sm"
          footer={
            <>
              <Button variant="ghost" onClick={() => setPasswordOpen(false)}>取消</Button>
              <Button variant="primary" loading={changing} onClick={() => void changePassword()}>更新密码</Button>
            </>
          }
        >
          <Field label="当前密码">
            <Input type="password" value={current} onChange={(event) => setCurrent(event.target.value)} autoComplete="current-password" />
          </Field>
          <Field label="新密码" hint="至少 8 位">
            <Input type="password" value={next} onChange={(event) => setNext(event.target.value)} autoComplete="new-password" />
          </Field>
        </Modal>
      </>
    );
  }

  function ModelSection({ onModel }: { onModel: (model: ModelStatus) => void }) {
    const [apiKey, setApiKey] = useState("");
    const [baseUrl, setBaseUrl] = useState(settings!.model_base_url || "https://api.deepseek.com");
    const [modelName, setModelName] = useState(settings!.model_name || "deepseek-chat");
    const [testing, setTesting] = useState(false);
    const [removing, setRemoving] = useState(false);

    async function saveKey() {
      if (apiKey.trim().length < 8) {
        toast("请输入有效的 API Key", "error");
        return;
      }
      setTesting(true);
      try {
        const response = await api<{ model: ModelStatus }>("/settings/model-key", {
          method: "POST",
          body: { api_key: apiKey.trim(), base_url: baseUrl.trim(), model_name: modelName.trim() },
        });
        onModel(response.model);
        await refresh();
        setApiKey("");
        toast("连接测试通过，模型已启用", "success");
      } catch (error) {
        toast((error as Error).message || "模型连接测试失败", "error");
      } finally {
        setTesting(false);
      }
    }

    async function removeKey() {
      setRemoving(true);
      try {
        const response = await api<{ model: ModelStatus }>("/settings/model-key", { method: "DELETE" });
        onModel(response.model);
        await refresh();
        toast("已移除 API Key，切换为本地抽取模式", "info");
      } catch {
        toast("移除失败", "error");
      } finally {
        setRemoving(false);
      }
    }

    return (
      <>
        <SectionCard title="AI 模型配置" description="支持任何 OpenAI 兼容的 Chat Completions 端点；默认使用 DeepSeek。">
          <div className={cn("model-status", model?.configured ? "live" : "local")}>
            <span className="model-status-icon">{model?.configured ? <Cpu size={18} /> : <AlertTriangle size={18} />}</span>
            <div>
              <strong>{model?.configured ? "已连接生成式模型" : "当前为本地抽取模式"}</strong>
              <p>
                {model?.configured
                  ? "模型 " + model.model + " · " + (model.source === "user" ? "使用你的个人密钥" : "使用服务器环境密钥")
                  : "回答由真实检索片段组成，不做生成式改写；翻译与图表解释不可用。"}
              </p>
            </div>
            {model?.configured && <Badge tone="accent">可用</Badge>}
          </div>

          <div className="model-form">
            <Field label="API Key" hint="仅保存在服务端，使用 AES 加密（Fernet）存储，接口永不返回明文">
              <Input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={model?.configured ? "已配置，如需更换请输入新 Key" : "sk-..."} autoComplete="off" />
            </Field>
            <div className="form-grid">
              <Field label="API Base URL" hint="例如 https://api.deepseek.com">
                <Input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
              </Field>
              <Field label="模型名称">
                <Input value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="deepseek-chat" />
              </Field>
            </div>
            <div className="section-actions">
              <Button variant="primary" loading={testing} onClick={() => void saveKey()}>
                测试连接并保存
              </Button>
              {model?.configured && (
                <Button variant="ghost" loading={removing} onClick={() => void removeKey()}>
                  移除密钥
                </Button>
              )}
            </div>
          </div>

          <div className="info-box">
            <KeyRound size={16} />
            <div>
              <strong>密钥如何使用</strong>
              <p>服务端在每次请求时解密密钥并转发到模型 API；前端、日志与错误信息中都不会出现密钥明文。</p>
            </div>
          </div>

          <div className="info-box">
            <Shield size={16} />
            <div>
              <strong>能力边界</strong>
              <p>模型不支持图片输入，因此图表解释基于图注与表格文本，而不是直接“看图”。所有生成式结论仍需你核对原文。</p>
            </div>
          </div>
        </SectionCard>
      </>
    );
  }

  function ParamsSection() {
    const [temperature, setTemperature] = useState(settings!.temperature);
    const [maxTokens, setMaxTokens] = useState(settings!.max_tokens);
    const [saving, setSaving] = useState(false);

    async function save() {
      setSaving(true);
      try {
        await updateSettings({ temperature, max_tokens: maxTokens });
        toast("模型参数已保存", "success");
      } catch {
        toast("保存失败", "error");
      } finally {
        setSaving(false);
      }
    }

    return (
      <SectionCard title="模型参数" description="较低的温度更稳定，适合论文总结；较高温度适合发散性研究讨论。">
        <Field label={"温度 · " + temperature.toFixed(2)} hint="0 最确定，1.5 最发散。科研场景建议 0.2-0.4。">
          <input
            type="range"
            min={0}
            max={1.5}
            step={0.05}
            value={temperature}
            onChange={(event) => setTemperature(Number(event.target.value))}
            className="range"
          />
        </Field>
        <Field label="最大输出 Token" hint="256 - 8000">
          <Input type="number" min={256} max={8000} value={maxTokens} onChange={(event) => setMaxTokens(Number(event.target.value))} />
        </Field>
        <div className="section-actions">
          <Button variant="primary" loading={saving} onClick={() => void save()}>保存参数</Button>
        </div>
      </SectionCard>
    );
  }

  function ReadingSection() {
    const [fontSize, setFontSize] = useState(settings!.reading_font_size);
    const [mode, setMode] = useState(settings!.default_summary_mode);
    const [saving, setSaving] = useState(false);

    async function save() {
      setSaving(true);
      try {
        await updateSettings({ reading_font_size: fontSize, default_summary_mode: mode });
        toast("阅读偏好已保存", "success");
      } catch {
        toast("保存失败", "error");
      } finally {
        setSaving(false);
      }
    }

    return (
      <SectionCard title="阅读偏好" description="这些设置会影响阅读器与总结面板的默认行为。">
        <Field label={"阅读字号 · " + fontSize + "px"}>
          <input type="range" min={13} max={24} step={1} value={fontSize} onChange={(event) => setFontSize(Number(event.target.value))} className="range" />
        </Field>
        <Field label="默认总结方式">
          <Select value={mode} onChange={(event) => setMode(event.target.value)}>
            {SUMMARY_MODES.map((item) => (
              <option key={item.id} value={item.id}>{item.label} · {item.hint}</option>
            ))}
          </Select>
        </Field>
        <div className="section-actions">
          <Button variant="primary" loading={saving} onClick={() => void save()}>保存偏好</Button>
        </div>
      </SectionCard>
    );
  }

  function LanguageSection() {
    const [language, setLanguage] = useState(settings!.language);
    const [target, setTarget] = useState(settings!.translation_language);
    const [style, setStyle] = useState(settings!.translation_style);
    const [saving, setSaving] = useState(false);

    async function save() {
      setSaving(true);
      try {
        await updateSettings({ language, translation_language: target, translation_style: style });
        toast("语言设置已保存", "success");
      } catch {
        toast("保存失败", "error");
      } finally {
        setSaving(false);
      }
    }

    return (
      <SectionCard title="语言与翻译" description="界面语言目前完整支持简体中文，英文界面正在开发中。">
        <div className="form-grid">
          <Field label="界面语言">
            <Select value={language} onChange={(event) => setLanguage(event.target.value)}>
              <option value="zh">简体中文</option>
              <option value="en">English（界面翻译中）</option>
            </Select>
          </Field>
          <Field label="翻译目标语言">
            <Select value={target} onChange={(event) => setTarget(event.target.value)}>
              <option value="简体中文">简体中文</option>
              <option value="English">English</option>
              <option value="日本語">日本語</option>
              <option value="한국어">한국어</option>
              <option value="Deutsch">Deutsch</option>
              <option value="Français">Français</option>
            </Select>
          </Field>
        </div>
        <Field label="翻译风格">
          <Select value={style} onChange={(event) => setStyle(event.target.value)}>
            <option value="academic">学术直译（保留术语与公式）</option>
            <option value="readable">通顺优先（适合快速理解）</option>
            <option value="literal">逐句对照</option>
          </Select>
        </Field>
        <div className="section-actions">
          <Button variant="primary" loading={saving} onClick={() => void save()}>保存设置</Button>
        </div>
      </SectionCard>
    );
  }

  function AppearanceSection() {
    return (
      <SectionCard title="主题设置" description="浅色主题为默认，适合长时间阅读。">
        <div className="theme-grid">
          {[
            { id: "light", label: "浅色", hint: "纸张质感 · 默认" },
            { id: "dark", label: "深色", hint: "夜间阅读" },
            { id: "system", label: "跟随系统", hint: "自动切换" },
          ].map((option) => (
            <button
              key={option.id}
              className={cn("theme-card", "theme-" + option.id, settings!.theme === option.id && "active")}
              onClick={() => void setTheme(option.id as "light" | "dark" | "system")}
            >
              <span className="theme-preview">
                <span className="theme-preview-side" />
                <span className="theme-preview-main" />
              </span>
              <strong>{option.label}</strong>
              <small>{option.hint}</small>
              {settings!.theme === option.id && <Check size={14} className="theme-check" />}
            </button>
          ))}
        </div>
      </SectionCard>
    );
  }

  function DataSection() {
    const [usage, setUsage] = useState<{ last_30_days: Record<string, number>; papers: number; pages: number; storage_bytes: number } | null>(null);
    const [exports, setExports] = useState<ExportRecord[]>([]);
    const [busy, setBusy] = useState(false);
    const [loading, setLoading] = useState(true);

    const load = useCallback(async () => {
      setLoading(true);
      try {
        const [usageResponse, exportResponse] = await Promise.all([
          api<{ last_30_days: Record<string, number>; papers: number; pages: number; storage_bytes: number }>("/settings/usage"),
          api<{ items: ExportRecord[] }>("/exports"),
        ]);
        setUsage(usageResponse);
        setExports(exportResponse.items);
      } catch {
        toast("无法加载数据统计", "error");
      } finally {
        setLoading(false);
      }
    }, [toast]);

    useEffect(() => {
      void load();
    }, [load]);

    async function exportAccount() {
      setBusy(true);
      try {
        const response = await api<{ export: ExportRecord }>("/settings/data-export", { method: "POST" });
        await downloadFile(response.export.download_url, response.export.filename);
        toast("账号数据已导出", "success");
        void load();
      } catch {
        toast("导出失败", "error");
      } finally {
        setBusy(false);
      }
    }

    async function removeExport(record: ExportRecord) {
      try {
        await api("/exports/" + record.id, { method: "DELETE" });
        setExports((current) => current.filter((item) => item.id !== record.id));
      } catch {
        toast("删除失败", "error");
      }
    }

    return (
      <>
        <SectionCard title="数据与存储" description="你的数据保存在服务端数据库中，文件保存在独立目录。">
          {loading ? (
            <div className="settings-loading"><Spinner size={18} /></div>
          ) : (
            <div className="usage-grid">
              <div><strong>{usage?.papers ?? 0}</strong><span>论文</span></div>
              <div><strong>{usage?.pages ?? 0}</strong><span>解析页数</span></div>
              <div><strong>{formatBytes(usage?.storage_bytes)}</strong><span>PDF 占用</span></div>
              <div><strong>{usage?.last_30_days?.chat ?? 0}</strong><span>近 30 天对话</span></div>
            </div>
          )}
          <div className="section-actions">
            <Button variant="secondary" icon={<Download size={14} />} loading={busy} onClick={() => void exportAccount()}>
              导出账号全部数据（JSON）
            </Button>
          </div>
        </SectionCard>

        <SectionCard title="导出记录" description="所有通过 PaperLens 生成的文件都会保存在这里。">
          {exports.length === 0 ? (
            <p className="muted">还没有导出记录。在论文总结或多论文对比中点击“导出”即可生成文件。</p>
          ) : (
            <ul className="export-list">
              {exports.slice(0, 12).map((record) => (
                <li key={record.id}>
                  <FileText size={15} />
                  <div>
                    <strong>{record.title}</strong>
                    <span>{record.format.toUpperCase()} · {formatBytes(record.size_bytes)} · {formatDate(record.created_at)}</span>
                  </div>
                  <button onClick={() => void downloadFile(record.download_url, record.filename)}>下载</button>
                  <button className="danger-text" onClick={() => void removeExport(record)} aria-label="删除导出记录"><Trash2 size={14} /></button>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>
      </>
    );
  }

  function ApiSection() {
    return (
      <>
        <SectionCard title="API 配置" description="PaperLens 使用 OpenAI 兼容的 Chat Completions 协议；所有模型调用都由后端代理。">
          <div className="api-rows">
            <div><span>协议</span><strong>OpenAI Chat Completions</strong></div>
            <div><span>Base URL</span><strong>{settings!.model_base_url || "https://api.deepseek.com"}</strong></div>
            <div><span>模型</span><strong>{model?.model || settings!.model_name || "deepseek-chat"}</strong></div>
            <div><span>状态</span><strong>{model?.configured ? "已配置（服务端代理）" : "未配置 · 本地抽取模式"}</strong></div>
          </div>
          <div className="api-endpoints">
            <span>应用内部接口（需登录 Token）</span>
            <code>POST /api/chat/stream</code>
            <code>POST /api/papers/{"{id}"}/summary</code>
            <code>POST /api/research/compare</code>
            <code>POST /api/exports</code>
          </div>
          <div className="section-actions">
            <Button variant="secondary" onClick={() => window.open("/api/docs", "_blank", "noopener")}>
              打开 API 文档
            </Button>
            <Button variant="ghost" onClick={() => go("model")}>
              配置模型密钥
            </Button>
          </div>
          <div className="info-box">
            <Shield size={16} />
            <div>
              <strong>密钥不会暴露给浏览器</strong>
              <p>前端只调用 PaperLens 自己的接口；模型密钥在服务端解密后使用，任何 API 响应都不会包含明文密钥。</p>
            </div>
          </div>
        </SectionCard>
      </>
    );
  }

  function PrivacySection() {
    const [open, setOpen] = useState(false);
    const [password, setPassword] = useState("");
    const [confirm, setConfirm] = useState("");
    const [deleting, setDeleting] = useState(false);

    async function deleteAccount() {
      if (confirm !== "DELETE") {
        toast("请输入 DELETE 以确认", "error");
        return;
      }
      setDeleting(true);
      try {
        await api("/settings/account", { method: "DELETE", body: { password, confirm } });
        setToken(null);
        logout();
        toast("账号与数据已删除", "success");
        navigate("/");
      } catch (error) {
        toast((error as Error).message || "删除失败", "error");
      } finally {
        setDeleting(false);
      }
    }

    return (
      <>
        <SectionCard title="隐私与数据隔离" description="论文是私有研究资料，不同账号之间不能互相读取。">
          <ul className="privacy-list">
            <li><Eye size={15} /><div><strong>行级权限</strong><p>所有论文、切片、批注、知识条目都带用户 ID，接口层强制校验归属，越权访问返回 404。</p></div></li>
            <li><Shield size={15} /><div><strong>提示注入防护</strong><p>论文正文只作为“被引用的资料”进入模型上下文，系统提示明确禁止把论文中的指令当作系统指令执行。</p></div></li>
            <li><Database size={15} /><div><strong>文件存储</strong><p>PDF 与图表保存在按用户隔离的目录，路径在服务端解析并校验，禁止路径穿越。</p></div></li>
            <li><KeyRound size={15} /><div><strong>密钥加密</strong><p>个人 API Key 使用 Fernet 对称加密存储，接口只返回是否已配置，不返回密钥。</p></div></li>
          </ul>
        </SectionCard>

        <SectionCard title="删除账号" description="此操作会永久删除论文、批注、知识、项目与对话，无法恢复。">
          <div className="danger-zone">
            <AlertTriangle size={18} />
            <div>
              <strong>危险操作</strong>
              <p>建议先在「数据管理」中导出账号数据。</p>
            </div>
            <Button variant="danger" onClick={() => setOpen(true)}>删除账号</Button>
          </div>
        </SectionCard>

        <Modal
          open={open}
          onClose={() => setOpen(false)}
          title="永久删除账号"
          size="sm"
          footer={
            <>
              <Button variant="ghost" onClick={() => setOpen(false)}>取消</Button>
              <Button variant="danger" loading={deleting} onClick={() => void deleteAccount()}>永久删除</Button>
            </>
          }
        >
          <p className="muted small">这会立即删除你的全部研究数据与文件。请输入密码，并输入 DELETE 确认。</p>
          <Field label="密码">
            <Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
          </Field>
          <Field label="输入 DELETE">
            <Input value={confirm} onChange={(event) => setConfirm(event.target.value)} placeholder="DELETE" />
          </Field>
        </Modal>
      </>
    );
  }

  function AboutSection() {
    return (
      <>
        <SectionCard title="关于 PaperLens AI · 知研" description="Your Personal AI Research Companion">
          <p className="about-text">
            PaperLens 是一个以 AI Agent 为核心的科研工作平台。它先检索论文原文，再回答问题；
            所有结论都附带页码与引用，并把重要的发现沉淀为可长期复用的个人知识。
          </p>
          <div className="about-grid">
            <div><span>版本</span><strong>0.9.0</strong></div>
            <div><span>后端</span><strong>FastAPI · SQLAlchemy</strong></div>
            <div><span>前端</span><strong>React · TypeScript · pdf.js</strong></div>
            <div><span>检索</span><strong>BM25 + n-gram 混合</strong></div>
            <div><span>PDF</span><strong>PyMuPDF 布局解析</strong></div>
            <div><span>模型</span><strong>DeepSeek（OpenAI 兼容）</strong></div>
          </div>
        </SectionCard>
        <SectionCard title="能力边界" description="明确说明，避免误解：">
          <ul className="about-boundaries">
            <li>本地抽取模式不会生成新文本，只从原文中抽取、排序与并列证据。</li>
            <li>模型不支持视觉输入，图表解释基于图注与表格文本，不读取像素内容。</li>
            <li>检索为词法 + 字符 n-gram 混合索引，不是神经向量检索；语义改写能力强的问题建议换用论文中的术语。</li>
            <li>研究缺口仅为基于资料库的候选线索，不等于对整个领域的空白判断。</li>
            <li>所有生成式结论仍需你回到原文核验后再用于正式写作。</li>
          </ul>
        </SectionCard>
      </>
    );
  }
}

function SectionCard({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <Card className="settings-card">
      <header>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </header>
      <div className="settings-card-body">{children}</div>
    </Card>
  );
}