import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import { ExternalLink, X } from "lucide-react";

export interface Source {
  n: number;
  title: string;
  url: string;
  host: string;
}

export type SourceMap = Map<number, Source>;

// Ищем секцию "## Источники" / "## Sources" / "**Источники**" и т.п.
// Допускаем 1–4 решётки, опциональное двоеточие, вариации: «Список источников»,
// «Использованные источники», «References».
const SOURCES_HEADING_RE =
  /^(?:#{1,4}\s+|\*\*)\s*(?:Список\s+|Использованн(?:ые|ых)\s+)?(?:Источник(?:и|ов)|Sources?|References?|Литература|Библиография)\s*:?\s*\*{0,2}\s*$/im;

// Строка источника. Покрываем форматы:
//   [1] Title: https://example.com
//   [1] Title — https://example.com
//   [1] Title | https://example.com
//   [1] Title (https://example.com)
//   [1] [Title](https://example.com)
//   [1] https://example.com                     (без title)
//   - [1] Title: https://example.com            (буллет)
//   1. [1] Title: https://example.com           (нумерованный)
const CITATION_LINE_MD_LINK_RE =
  /^\s*(?:[-*+]\s+|\d+\.\s+)?\[(\d+)\]\s*\[([^\]]+?)\]\(<?\s*(https?:\/\/[^\s)>]+)\s*>?\)/;
const CITATION_LINE_PLAIN_RE =
  /^\s*(?:[-*+]\s+|\d+\.\s+)?\[(\d+)\]\s*(.*?)\s*[:：—–\-|]\s*<?(https?:\/\/\S+?)>?\s*[).,;]*\s*$/;
const CITATION_LINE_URL_ONLY_RE =
  /^\s*(?:[-*+]\s+|\d+\.\s+)?\[(\d+)\]\s*<?(https?:\/\/\S+?)>?\s*[).,;]*\s*$/;
const CITATION_LINE_PAREN_RE =
  /^\s*(?:[-*+]\s+|\d+\.\s+)?\[(\d+)\]\s*(.+?)\s*\(<?\s*(https?:\/\/[^\s)>]+)\s*>?\)\s*$/;

const hostOf = (url: string): string => {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
};

function parseCitationLine(
  rawLine: string,
): { n: number; title: string; url: string } | null {
  let m = rawLine.match(CITATION_LINE_MD_LINK_RE);
  if (m) return { n: Number(m[1]), title: m[2].trim(), url: m[3] };
  m = rawLine.match(CITATION_LINE_PAREN_RE);
  if (m) return { n: Number(m[1]), title: m[2].trim(), url: m[3] };
  m = rawLine.match(CITATION_LINE_PLAIN_RE);
  if (m) return { n: Number(m[1]), title: m[2].trim(), url: m[3] };
  m = rawLine.match(CITATION_LINE_URL_ONLY_RE);
  if (m) return { n: Number(m[1]), title: "", url: m[2] };
  return null;
}

export function parseSources(markdown: string | null | undefined): SourceMap {
  const map: SourceMap = new Map();
  if (!markdown) return map;

  let section: string | null = null;

  const headingMatch = markdown.match(SOURCES_HEADING_RE);
  if (headingMatch) {
    const start = markdown.indexOf(headingMatch[0]) + headingMatch[0].length;
    const rest = markdown.slice(start);
    const nextHeading = rest.search(/^\s*#{1,4}\s+\S/m);
    section = nextHeading === -1 ? rest : rest.slice(0, nextHeading);
  } else {
    // Fallback: берём последний блок документа, где подряд идут строки `[N] ... url`.
    // Это на случай, если LLM забыл заголовок или назвал его нестандартно.
    const lines = markdown.split(/\r?\n/);
    let blockEnd = -1;
    for (let i = lines.length - 1; i >= 0; i--) {
      if (parseCitationLine(lines[i])) {
        blockEnd = i;
        break;
      }
    }
    if (blockEnd !== -1) {
      let blockStart = blockEnd;
      while (
        blockStart > 0 &&
        (parseCitationLine(lines[blockStart - 1]) ||
          lines[blockStart - 1].trim() === "")
      ) {
        blockStart--;
      }
      section = lines.slice(blockStart, blockEnd + 1).join("\n");
    }
  }

  if (!section) return map;

  for (const rawLine of section.split(/\r?\n/)) {
    const parsed = parseCitationLine(rawLine);
    if (!parsed) continue;
    if (!Number.isFinite(parsed.n) || map.has(parsed.n)) continue;
    const cleaned = parsed.title.replace(/^["'«]+|["'»]+$/g, "").trim();
    const title = cleaned === parsed.url ? "" : cleaned;
    map.set(parsed.n, {
      n: parsed.n,
      title,
      url: parsed.url,
      host: hostOf(parsed.url),
    });
  }
  return map;
}

interface CitationsContextValue {
  sources: SourceMap;
  openDrawer: (focus?: number[]) => void;
}

const CitationsContext = createContext<CitationsContextValue | null>(null);

export const useCitations = () => useContext(CitationsContext);

const faviconUrl = (host: string) =>
  `https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=64`;

interface CitationChipProps {
  nums: number[];
}

export const CitationChip: React.FC<CitationChipProps> = ({ nums }) => {
  const ctx = useCitations();
  if (!ctx) return <>[{nums.join(", ")}]</>;

  const resolved = nums
    .map((n) => ctx.sources.get(n))
    .filter((s): s is Source => !!s);

  if (resolved.length === 0) return <>[{nums.join(", ")}]</>;

  const visible = resolved.slice(0, 3);
  const extra = resolved.length - visible.length;
  const title = resolved
    .map((s) => `[${s.n}] ${s.title || s.host}`)
    .join("\n");

  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        ctx.openDrawer(nums);
      }}
      title={title}
      className="inline-flex items-center align-middle gap-0.5 mx-0.5 rounded-full bg-muted hover:bg-accent transition-colors px-1 py-0.5 text-xs cursor-pointer border border-border"
    >
      <span className="inline-flex">
        {visible.map((s, i) => (
          <img
            key={s.n}
            src={faviconUrl(s.host)}
            alt=""
            loading="lazy"
            className="h-4 w-4 rounded-full bg-background ring-1 ring-border"
            style={{ marginLeft: i === 0 ? 0 : -6 }}
            onError={(ev) => {
              (ev.target as HTMLImageElement).style.visibility = "hidden";
            }}
          />
        ))}
      </span>
      {extra > 0 && (
        <span className="ml-1 text-muted-foreground">+{extra}</span>
      )}
    </button>
  );
};

interface CitationsDrawerProps {
  sources: SourceMap;
  open: boolean;
  focus: number[];
  onClose: () => void;
}

const CitationsDrawer: React.FC<CitationsDrawerProps> = ({
  sources,
  open,
  focus,
  onClose,
}) => {
  const focusSet = useMemo(() => new Set(focus), [focus]);
  const list = useMemo(
    () => Array.from(sources.values()).sort((a, b) => a.n - b.n),
    [sources],
  );

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-[70] bg-black/20"
          onClick={onClose}
          aria-hidden
        />
      )}
      <aside
        className={[
          "fixed top-0 right-0 bottom-0 z-[71] w-full max-w-[420px] bg-card border-l border-border shadow-lg transition-transform duration-200 ease-out flex flex-col",
          open ? "translate-x-0" : "translate-x-full",
        ].join(" ")}
        aria-hidden={!open}
      >
        <header className="flex items-center justify-between p-4 border-b border-border">
          <h3 className="text-base font-semibold">Источники ({list.length})</h3>
          <button
            type="button"
            onClick={onClose}
            title="Закрыть"
            className="p-1 rounded hover:bg-accent cursor-pointer"
          >
            <X size={18} />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {list.map((s) => {
            const highlighted = focusSet.has(s.n);
            return (
              <a
                key={s.n}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className={[
                  "flex gap-3 p-3 rounded-lg border transition-colors",
                  highlighted
                    ? "border-primary bg-primary/5"
                    : "border-border hover:bg-accent",
                ].join(" ")}
              >
                <img
                  src={faviconUrl(s.host)}
                  alt=""
                  loading="lazy"
                  className="h-6 w-6 rounded mt-0.5 flex-shrink-0"
                  onError={(ev) => {
                    (ev.target as HTMLImageElement).style.visibility = "hidden";
                  }}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground mb-0.5">
                    <span className="truncate">{s.host}</span>
                    <ExternalLink size={12} className="flex-shrink-0" />
                  </div>
                  <div className="text-sm text-foreground line-clamp-3 break-words">
                    <span className="text-muted-foreground mr-1">[{s.n}]</span>
                    {s.title || s.host}
                  </div>
                </div>
              </a>
            );
          })}
        </div>
      </aside>
    </>
  );
};

interface CitationsProviderProps {
  sources: SourceMap;
  children: React.ReactNode;
}

export const CitationsProvider: React.FC<CitationsProviderProps> = ({
  sources,
  children,
}) => {
  const [open, setOpen] = useState(false);
  const [focus, setFocus] = useState<number[]>([]);

  const openDrawer = useCallback((nums?: number[]) => {
    setFocus(nums ?? []);
    setOpen(true);
  }, []);

  const value = useMemo(() => ({ sources, openDrawer }), [sources, openDrawer]);

  return (
    <CitationsContext.Provider value={value}>
      {children}
      <CitationsDrawer
        sources={sources}
        open={open}
        focus={focus}
        onClose={() => setOpen(false)}
      />
    </CitationsContext.Provider>
  );
};

// `[1]`, `[1, 2]`, `[1,2,3]` — но НЕ `[abc]` и не markdown-ссылки `[txt](url)`.
const CITATION_INLINE_RE = /\[(\d+(?:\s*,\s*\d+)*)\](?!\()/g;

export function transformCitationsInChildren(
  children: React.ReactNode,
): React.ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child === "string") {
      return splitCitationString(child);
    }
    if (React.isValidElement(child)) {
      // не трогаем содержимое code/pre
      const type = (child.type as any)?.displayName || child.type;
      if (type === "code" || type === "pre") return child;
      const anyProps = child.props as any;
      if (!anyProps?.children) return child;
      return React.cloneElement(
        child,
        anyProps,
        transformCitationsInChildren(anyProps.children),
      );
    }
    return child;
  });
}

function splitCitationString(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  CITATION_INLINE_RE.lastIndex = 0;
  while ((m = CITATION_INLINE_RE.exec(text))) {
    if (m.index > lastIndex) parts.push(text.slice(lastIndex, m.index));
    const nums = m[1]
      .split(",")
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n));
    parts.push(<CitationChip key={`c-${m.index}-${m[0]}`} nums={nums} />);
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts.length ? parts : [text];
}

// Текстовая версия SOURCES_HEADING_RE — для матчинга по тексту heading-узла в mdast,
// где сам символ # уже не входит в текст.
const SOURCES_HEADING_TEXT_RE =
  /^\s*(?:Список\s+|Использованн(?:ые|ых)\s+)?(?:Источник(?:и|ов)|Sources?|References?|Литература|Библиография)\s*:?\s*$/i;

function mdastNodeText(node: any): string {
  if (!node) return "";
  if (node.type === "break") return "\n";
  if (node.type === "link") {
    const inner = (node.children || []).map(mdastNodeText).join("");
    return `[${inner}](${node.url})`;
  }
  if (typeof node.value === "string") return node.value;
  if (Array.isArray(node.children)) {
    const isBlock = ["root", "list", "listItem", "blockquote"].includes(
      node.type,
    );
    return node.children.map(mdastNodeText).join(isBlock ? "\n" : "");
  }
  return "";
}

function nodeHasOnlyCitationLines(node: any): boolean {
  const text = mdastNodeText(node);
  if (!text.trim()) return false;
  for (const line of text.split(/\r?\n/)) {
    if (line.trim() === "") continue;
    if (!parseCitationLine(line)) return false;
  }
  return true;
}

// Remark-плагин: находит секцию «Источники» в mdast и заменяет её на placeholder
// <sources-list/>, который рендерится кастомным компонентом в react-markdown.
// Сами данные источников приходят отдельно через CitationsContext.
export const remarkSources = () => {
  return (tree: any) => {
    const children = tree?.children;
    if (!Array.isArray(children) || children.length === 0) return;

    let sectionStart = -1;
    let sectionEnd = -1;

    for (let i = 0; i < children.length; i++) {
      const node = children[i];
      if (node.type === "heading") {
        const text = mdastNodeText(node).trim();
        if (SOURCES_HEADING_TEXT_RE.test(text)) {
          sectionStart = i;
          break;
        }
      }
    }

    if (sectionStart !== -1) {
      sectionEnd = children.length;
      for (let i = sectionStart + 1; i < children.length; i++) {
        if (children[i].type === "heading") {
          sectionEnd = i;
          break;
        }
      }
    } else {
      // Fallback: хвост документа из подряд идущих узлов, в которых только citation-строки.
      for (let i = children.length - 1; i >= 0; i--) {
        if (nodeHasOnlyCitationLines(children[i])) {
          sectionEnd = i + 1;
          sectionStart = i;
          for (let j = i - 1; j >= 0; j--) {
            if (nodeHasOnlyCitationLines(children[j])) sectionStart = j;
            else break;
          }
          break;
        }
      }
    }

    if (sectionStart === -1) return;

    // Подстрахуемся: вырезаем секцию только если внутри реально есть хоть одна citation-строка.
    let hasCitations = false;
    for (let i = sectionStart; i < sectionEnd && !hasCitations; i++) {
      const text = mdastNodeText(children[i]);
      for (const line of text.split(/\r?\n/)) {
        if (parseCitationLine(line)) {
          hasCitations = true;
          break;
        }
      }
    }
    if (!hasCitations) return;

    children.splice(sectionStart, sectionEnd - sectionStart, {
      type: "html",
      value: "<sources-list></sources-list>",
    });
  };
};

export const SourcesList: React.FC = () => {
  const ctx = useCitations();
  const list = useMemo(
    () =>
      ctx ? Array.from(ctx.sources.values()).sort((a, b) => a.n - b.n) : [],
    [ctx],
  );
  if (list.length === 0) return null;

  return (
    <section className="my-6">
      <h2 className="mt-8 mb-4 scroll-m-20 text-3xl font-semibold tracking-tight">
        Источники
      </h2>
      <ul className="list-none space-y-2 pl-0">
        {list.map((s) => (
          <li key={s.n} className="leading-7">
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-baseline gap-1.5 text-primary hover:underline break-words"
            >
              <img
                src={faviconUrl(s.host)}
                alt=""
                loading="lazy"
                className="h-4 w-4 self-center rounded-sm bg-background ring-1 ring-border flex-shrink-0"
                onError={(ev) => {
                  (ev.target as HTMLImageElement).style.visibility = "hidden";
                }}
              />
              <span>{s.title || s.url}</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
};
