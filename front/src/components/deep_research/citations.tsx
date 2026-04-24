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

// Ищем секцию "## Источники" или "## Sources" (ест и "#" любого уровня 2-3)
// и вытаскиваем строки вида "[N] Title: URL" до следующего заголовка или конца файла.
const SOURCES_HEADING_RE =
  /^#{2,3}\s+(Источники|Sources)\s*$/im;

const CITATION_LINE_RE =
  /^\s*(?:[-*+]\s+|\d+\.\s+)?\[(\d+)\]\s*(.+?)\s*[:：—–-]\s*(https?:\/\/\S+)\s*$/;

const hostOf = (url: string): string => {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
};

export function parseSources(markdown: string | null | undefined): SourceMap {
  const map: SourceMap = new Map();
  if (!markdown) return map;

  const headingMatch = markdown.match(SOURCES_HEADING_RE);
  if (!headingMatch) return map;

  const start = markdown.indexOf(headingMatch[0]) + headingMatch[0].length;
  const rest = markdown.slice(start);
  // до следующего заголовка того же/верхнего уровня
  const nextHeading = rest.search(/^\s*#{1,3}\s+\S/m);
  const section = nextHeading === -1 ? rest : rest.slice(0, nextHeading);

  for (const rawLine of section.split(/\r?\n/)) {
    const m = rawLine.match(CITATION_LINE_RE);
    if (!m) continue;
    const n = Number(m[1]);
    if (!Number.isFinite(n) || map.has(n)) continue;
    const title = m[2].trim().replace(/^["'«]+|["'»]+$/g, "");
    const url = m[3].replace(/[),.]+$/, "");
    map.set(n, { n, title, url, host: hostOf(url) });
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
  const title = resolved.map((s) => `[${s.n}] ${s.title}`).join("\n");

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
          <h3 className="text-base font-semibold">
            Источники ({list.length})
          </h3>
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
                    (ev.target as HTMLImageElement).style.visibility =
                      "hidden";
                  }}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground mb-0.5">
                    <span className="truncate">{s.host}</span>
                    <ExternalLink size={12} className="flex-shrink-0" />
                  </div>
                  <div className="text-sm text-foreground line-clamp-3 break-words">
                    <span className="text-muted-foreground mr-1">[{s.n}]</span>
                    {s.title}
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

  const value = useMemo(
    () => ({ sources, openDrawer }),
    [sources, openDrawer],
  );

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
    parts.push(
      <CitationChip key={`c-${m.index}-${m[0]}`} nums={nums} />,
    );
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts.length ? parts : [text];
}