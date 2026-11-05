import { Link } from "react-router-dom";
import {
  ArrowRight,
  BookMarked,
  BrainCircuit,
  FileSearch,
  Layers,
  Quote,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useApp } from "../store/AppContext";

export function Landing() {
  const { authed } = useApp();
  return (
    <div className="landing">
      <header className="landing-nav">
        <Link to="/" className="brand">
          <span className="brand-mark">
            <svg width="34" height="34" viewBox="0 0 64 64" aria-hidden="true">
              <rect width="64" height="64" rx="15" fill="#1F3B34" />
              <circle cx="28" cy="28" r="13" fill="none" stroke="#ECE7D9" strokeWidth="4" />
              <path d="M38 38 L50 50" stroke="#C8A96A" strokeWidth="5" strokeLinecap="round" />
              <path d="M20 30c5-8 11-8 16 0" stroke="#ECE7D9" strokeWidth="3" fill="none" strokeLinecap="round" />
            </svg>
          </span>
          <span>
            <strong>PaperLens</strong>
            <small>知研 AI</small>
          </span>
        </Link>
        <nav className="landing-links">
          <a href="#workflow">工作方式</a>
          <a href="#features">核心能力</a>
          <a href="#trust">数据与边界</a>
        </nav>
        <div className="landing-actions">
          {authed ? (
            <Link className="btn btn-primary btn-md" to="/app">
              进入研究空间 <ArrowRight size={15} />
            </Link>
          ) : (
            <>
              <Link className="btn btn-ghost btn-md" to="/login">
                登录
              </Link>
              <Link className="btn btn-primary btn-md" to="/register">
                免费开始
              </Link>
            </>
          )}
        </div>
      </header>

      <main>
        <section className="hero">
          <div className="hero-copy">
            <span className="eyebrow">
              <Sparkles size={14} /> Your Personal AI Research Companion
            </span>
            <h1>
              读懂论文，
              <br />
              更要<span className="hero-accent">记得住、追得回</span>。
            </h1>
            <p className="hero-sub">
              PaperLens 是面向研究生与科研人员的 AI 科研智能体。它先检索论文原文，再回答问题；
              每一条结论都带页码与引用，重要的发现沉淀成可长期复用的个人知识库。
            </p>
            <div className="hero-actions">
              <Link className="btn btn-primary btn-lg" to={authed ? "/app" : "/register"}>
                {authed ? "回到研究空间" : "开始第一次论文研究"} <ArrowRight size={16} />
              </Link>
              <a className="btn btn-secondary btn-lg" href="#workflow">
                看看它怎么工作
              </a>
            </div>
            <ul className="hero-points">
              <li><ShieldCheck size={15} /> 论文私有，数据隔离</li>
              <li><Quote size={15} /> 回答附带原文页码</li>
              <li><BookMarked size={15} /> 结论可保存、可关联</li>
            </ul>
          </div>

          <div className="hero-visual" aria-hidden="true">
            <div className="mock-window">
              <div className="mock-bar">
                <span className="mock-dot" />
                <span className="mock-dot" />
                <span className="mock-dot" />
                <span className="mock-title">Grounded Retrieval for Scientific Reading</span>
              </div>
              <div className="mock-body">
                <div className="mock-question">这篇论文如何保证回答可以追溯？</div>
                <div className="mock-answer">
                  <div className="mock-agent">
                    <span className="mock-pulse" /> 已检索 6 个原文片段
                  </div>
                  <p>
                    论文提出的来源契约要求每个切片保存页码、章节与边界框，生成后再做引用校验<sup className="mock-cite">2</sup>。
                    消融实验显示，去掉章节感知切片会使忠实度下降 9.1 个点<sup className="mock-cite">5</sup>。
                  </p>
                  <div className="mock-sources">
                    <div>
                      <span className="mock-key">C2</span>
                      <span>3 Method · p.2</span>
                    </div>
                    <div>
                      <span className="mock-key">C5</span>
                      <span>4 Experiments · p.3</span>
                    </div>
                  </div>
                </div>
              </div>
              <div className="mock-composer">
                <span>追问：这套评估方法有哪些局限？</span>
                <span className="mock-send">发送</span>
              </div>
            </div>
            <div className="mock-float mock-float-a">
              <Layers size={15} />
              <div>
                <strong>多论文对比</strong>
                <span>4 篇 · 方法与实验</span>
              </div>
            </div>
            <div className="mock-float mock-float-b">
              <BrainCircuit size={15} />
              <div>
                <strong>研究缺口</strong>
                <span>附证据与验证方式</span>
              </div>
            </div>
          </div>
        </section>

        <section className="landing-band" id="trust">
          <div>
            <strong>不编造论文内容</strong>
            <span>证据不足时明确说明，而不是给出看似合理的答案。</span>
          </div>
          <div>
            <strong>不做黑箱摘要</strong>
            <span>每个结论都能一键跳回 PDF 的对应页码与高亮位置。</span>
          </div>
          <div>
            <strong>不丢失研究过程</strong>
            <span>对话、批注、结论与项目长期保存，可导出为真实文件。</span>
          </div>
        </section>

        <section className="landing-section" id="workflow">
          <div className="section-head">
            <span className="eyebrow">Workflow</span>
            <h2>把“读论文”变成一段可积累的研究过程</h2>
            <p>从一篇 PDF 开始，逐步建立属于你的研究资产，而不是一次次从零开始的对话。</p>
          </div>
          <div className="workflow-grid">
            {[
              { step: "01", title: "上传与解析", text: "PDF 被切分为章节、段落与图表，保留页码和边界框；所有内容只属于你。", icon: FileSearch },
              { step: "02", title: "提问与核验", text: "选择研究模式提问，智能体先检索证据，再给出带 [C1] 引用的回答；点击引用回到原文。", icon: MessageSquareIcon },
              { step: "03", title: "沉淀与关联", text: "高亮、批注、AI 结论进入知识库，在项目中与论文和研究问题建立关联。", icon: BookMarked },
            ].map((item) => (
              <article key={item.step} className="workflow-card">
                <span className="workflow-step">{item.step}</span>
                <item.icon size={22} />
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="landing-section" id="features">
          <div className="section-head">
            <span className="eyebrow">Capabilities</span>
            <h2>为长期研究设计，而不是为演示设计</h2>
          </div>
          <div className="feature-grid">
            {[
              { icon: Quote, title: "可追溯的问答", text: "检索 → 证据 → 回答。引用卡片显示论文、页码、章节与原文片段，一键跳转。" },
              { icon: Layers, title: "多论文综合", text: "按方法、实验、创新点与局限横向对比；也可以自选片段进行比较。" },
              { icon: BrainCircuit, title: "批判性阅读", text: "区分作者声称、证据支撑与尚需验证的推断，指出方法与实验的边界。" },
              { icon: BookMarked, title: "个人知识库", text: "知识片段保留来源与页码，支持标签、项目、关联图谱与多种格式导出。" },
            ].map((item) => (
              <article key={item.title} className="feature-card">
                <span className="feature-icon"><item.icon size={19} /></span>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="landing-cta">
          <div>
            <h2>准备好把下一篇论文读透了吗？</h2>
            <p>创建账号，上传第一篇 PDF。没有 API Key 时，PaperLens 仍会用真实检索结果为你提供可核验的抽取式回答。</p>
          </div>
          <Link className="btn btn-primary btn-lg" to={authed ? "/app" : "/register"}>
            {authed ? "继续研究" : "创建免费账号"} <ArrowRight size={16} />
          </Link>
        </section>
      </main>

      <footer className="landing-foot">
        <span>PaperLens AI · 知研</span>
        <span>为认真的阅读而设计</span>
        <span>© {new Date().getFullYear()}</span>
      </footer>
    </div>
  );
}

function MessageSquareIcon(props: { size?: number }) {
  return <Sparkles size={props.size} />;
}
