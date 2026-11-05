import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, BookMarked, FileText, MessageSquareText, Sparkles } from "lucide-react";
import { useApp } from "../store/AppContext";
import { Button, Modal } from "./ui";
import { cn } from "../lib/utils";

const STEPS = [
  {
    icon: FileText,
    title: "把论文交给 PaperLens",
    text: "上传 PDF 后，系统会解析章节、段落、表格、图表和页码坐标。所有 AI 回答都能回到原文位置。",
  },
  {
    icon: MessageSquareText,
    title: "用研究问题驱动阅读",
    text: "选择一个研究模式，直接提问：方法是否合理？实验覆盖了哪些场景？多篇论文之间有什么分歧？",
  },
  {
    icon: BookMarked,
    title: "让结论沉淀下来",
    text: "把高亮、批注、AI 结论保存到个人知识库，并在项目中关联论文、观点与研究问题。",
  },
];

export function Onboarding() {
  const { updateSettings, toast } = useApp();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const current = STEPS[step];
  const Icon = current.icon;

  async function finish(go: string | null) {
    setSaving(true);
    try {
      await updateSettings({ onboarding_completed: true });
      if (go) navigate(go);
    } catch {
      toast("无法保存引导状态，可稍后在设置中完成", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      onClose={() => void finish(null)}
      size="md"
      footer={
        <>
          <button className="link-btn" onClick={() => void finish(null)}>
            跳过引导
          </button>
          <div className="modal-foot-actions">
            {step > 0 && (
              <Button variant="ghost" onClick={() => setStep((value) => value - 1)}>
                上一步
              </Button>
            )}
            {step < STEPS.length - 1 ? (
              <Button variant="primary" onClick={() => setStep((value) => value + 1)}>
                继续 <ArrowRight size={15} />
              </Button>
            ) : (
              <Button variant="primary" loading={saving} onClick={() => void finish("/app/papers")}>
                上传第一篇论文
              </Button>
            )}
          </div>
        </>
      }
    >
      <div className="onboarding">
        <div className="onboarding-steps">
          {STEPS.map((item, index) => (
            <span key={item.title} className={cn("onboarding-dot", index === step && "active", index < step && "done")} />
          ))}
        </div>
        <div className="onboarding-icon">
          <Icon size={26} />
        </div>
        <h2>{current.title}</h2>
        <p>{current.text}</p>
        <div className="onboarding-note">
          <Sparkles size={14} />
          <span>论文原文属于你的私有资料。AI 只在你选择的研究范围内检索，不会跨账号访问。</span>
        </div>
      </div>
    </Modal>
  );
}
