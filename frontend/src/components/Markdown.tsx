import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Check, Copy } from "lucide-react";
import { cn } from "../lib/utils";
import { copyText } from "../lib/api";

const CitationContext = createContext<{ onCite?: (key: string) => void }>({});

export function MarkdownView({
  content,
  onCite,
  className,
}: {
  content: string;
  onCite?: (key: string) => void;
  className?: string;
}) {
  const prepared = content.replace(/\[C(\d+)\]/g, "[C$1](#cite-C$1)");
  return (
    <CitationContext.Provider value={{ onCite }}>
      <div className={cn("markdown", className)}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeKatex]}
          components={{
            a: ({ href, children }) => {
              if (href?.startsWith("#cite-C")) {
                const key = href.replace("#cite-", "");
                return <CitationRef citeKey={key} />;
              }
              return (
                <a href={href} target="_blank" rel="noreferrer noopener">
                  {children}
                </a>
              );
            },
            pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
            table: ({ children }) => (
              <div className="table-scroll">
                <table>{children}</table>
              </div>
            ),
          }}
        >
          {prepared}
        </ReactMarkdown>
      </div>
    </CitationContext.Provider>
  );
}

function CitationRef({ citeKey }: { citeKey: string }) {
  const { onCite } = useContext(CitationContext);
  const label = citeKey.replace("C", "");
  return (
    <button
      type="button"
      className="citation-ref"
      title={"查看引用 " + citeKey}
      onClick={(event) => {
        event.preventDefault();
        onCite?.(citeKey);
      }}
    >
      {label}
    </button>
  );
}

function CodeBlock({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const text = extractText(children);
  return (
    <div className="code-block">
      <button
        className="code-copy"
        onClick={async () => {
          const ok = await copyText(text);
          if (ok) {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1600);
          }
        }}
      >
        {copied ? <Check size={13} /> : <Copy size={13} />}
        {copied ? "已复制" : "复制"}
      </button>
      <pre>{children}</pre>
    </div>
  );
}

function extractText(node: ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (node && typeof node === "object" && "props" in node) {
    const props = (node as unknown as { props?: { children?: ReactNode } }).props;
    return extractText(props?.children);
  }
  return "";
}