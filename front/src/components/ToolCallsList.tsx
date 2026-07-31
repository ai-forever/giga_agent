import React, { useEffect, useMemo, useRef, useState } from "react";
import { Ban, Check, Loader, Minus, Plus, X } from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { dracula } from "react-syntax-highlighter/dist/esm/styles/prism";
import type { Message } from "@langchain/langgraph-sdk";
import type { ToolCall } from "@langchain/core/messages/tool";
import type { UseStream } from "@langchain/langgraph-sdk/react";

import type { GraphState } from "../interfaces";
import { PROGRESS_AGENTS, TOOL_MAP } from "../config";
import OverlayPortal from "./OverlayPortal";
import MessageAttachment from "./attachments/MessageAttachment";
import { notifyIfHidden } from "../lib/notifications";
import {
  compositionFor,
  compositionFromResult,
  isResponseWidget,
  resolveWidget,
} from "./widgets/registry";
import { ComposedBoard } from "./widgets/kit";

const THINK_TOOL_NAME = "think";

interface DeepResearchSubQ {
  id: number;
  text: string;
  status?: string;
  queries?: string[];
}

const SUBQ_STATUS_STYLES: Record<string, string> = {
  pending: "bg-muted-foreground/40",
  searched: "bg-blue-400",
  read: "bg-amber-400",
  covered: "bg-emerald-500",
  gap: "bg-rose-500",
};

const DeepResearchPlan: React.FC<{ plan: DeepResearchSubQ[] }> = ({ plan }) => (
  <div className="mt-2 flex flex-col gap-1.5">
    {plan.map((sub) => {
      const dotCls =
        SUBQ_STATUS_STYLES[sub.status || "pending"] ||
        SUBQ_STATUS_STYLES.pending;
      return (
        <div key={sub.id} className="text-xs">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-2 w-2 rounded-full ${dotCls}`}
              aria-hidden
            />
            <span className="font-medium text-foreground">{sub.text}</span>
          </div>
          {sub.queries && sub.queries.length > 0 && (
            <div className="ml-4 mt-1 flex flex-wrap gap-1">
              {sub.queries.map((q, i) => (
                <span
                  key={i}
                  className="rounded bg-muted px-2 py-0.5 text-muted-foreground"
                >
                  {q}
                </span>
              ))}
            </div>
          )}
        </div>
      );
    })}
  </div>
);

const DeepResearchToolCall: React.FC<{
  toolCall: ToolCall;
  resultMessage?: Message;
  isStreaming: boolean;
  thread?: UseStream<GraphState>;
  onOpenAttachment: (att: any) => void;
}> = ({ toolCall, resultMessage, isStreaming, thread, onOpenAttachment }) => {
  const inFlight = isStreaming && !resultMessage;
  const isStopped =
    !!(resultMessage?.additional_kwargs as any)?.stopped_by_user ||
    (!resultMessage && !inFlight && !thread?.interrupt);
  const attachments: any[] =
    (resultMessage?.additional_kwargs?.tool_attachments as any[]) || [];

  const parsedPayload = useMemo(() => {
    if (!resultMessage) return null;
    try {
      return JSON.parse(resultMessage.content as string);
    } catch {
      return null;
    }
  }, [resultMessage]);

  const deepResearchPlan: DeepResearchSubQ[] | null = useMemo(() => {
    if (parsedPayload) {
      const inner = parsedPayload.data ?? parsedPayload;
      const plan = inner?.plan;
      if (Array.isArray(plan) && plan.length) return plan;
    }
    if (inFlight && thread) {
      // @ts-ignore
      const uis = (thread.values?.ui ?? []).filter(
        (el: any) =>
          el.name === "agent_execution" &&
          el.props?.tool_call_id === toolCall.id,
      );
      let latest: DeepResearchSubQ[] | null = null;
      for (const u of uis) {
        // @ts-ignore
        const p = u.props?.plan;
        if (Array.isArray(p) && p.length) latest = p;
      }
      return latest;
    }
    return null;
  }, [toolCall.id, parsedPayload, inFlight, thread]);

  const progressText: string | null = useMemo(() => {
    if (!inFlight || !thread) return null;
    // @ts-ignore
    const uis = (thread.values?.ui ?? []).filter(
      (el: any) =>
        el.name === "agent_execution" && el.props?.tool_call_id === toolCall.id,
    );
    const last = uis.at(-1);
    if (last?.props?.node_text) return String(last.props.node_text);
    // @ts-ignore
    return PROGRESS_AGENTS.run_deep_research?.[last?.props?.node] ?? null;
  }, [inFlight, thread, toolCall.id]);

  const topic = getStringArg((toolCall.args ?? {}) as Record<string, any>, [
    "research_topic",
  ]);

  return (
    <div className="my-1 rounded-lg border border-border/50 bg-muted/15 px-3 py-2">
      <div className="flex min-w-0 items-center gap-2 text-sm">
        {inFlight ? (
          <Loader
            size={14}
            className="shrink-0 animate-spin text-muted-foreground"
          />
        ) : isStopped ? (
          <Ban size={14} className="shrink-0 text-muted-foreground" />
        ) : (
          <Check size={14} className="shrink-0 text-emerald-500" />
        )}
        <span className="shrink-0 whitespace-nowrap font-medium text-foreground">
          {inFlight
            ? "Глубокое исследование"
            : isStopped
              ? "Исследование остановлено"
              : "Исследование завершено"}
        </span>
        {topic && (
          <span className="min-w-0 flex-1 truncate text-muted-foreground">
            {truncate(topic, 80)}
          </span>
        )}
      </div>
      {progressText && (
        <div className="mt-1 truncate text-xs text-transparent bg-gradient-to-r from-muted-foreground/40 via-muted-foreground/70 to-muted-foreground/40 bg-clip-text animate-pulse">
          {progressText}
        </div>
      )}
      {deepResearchPlan && <DeepResearchPlan plan={deepResearchPlan} />}
      {attachments.length > 0 && (
        <div className="mt-2 flex flex-col gap-0.5">
          {attachments.map((att) => {
            const attachmentPath = att.sandbox_path ?? att.path;
            if (!attachmentPath) return null;
            const attachmentName =
              att.original_name ?? attachmentPath.split("/").at(-1);
            const label =
              ATTACHMENT_TEXTS[att.file_type ?? "text"] ??
              ATTACHMENT_TEXTS.other;
            return (
              <a
                key={attachmentPath}
                href=""
                onClick={(ev) => {
                  ev.preventDefault();
                  onOpenAttachment(att);
                }}
                className="truncate text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
              >
                {label} · {attachmentName}
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
};

const ATTACHMENT_TEXTS: Record<string, string> = {
  plotly_graph: "Создан график",
  image: "Создано изображение",
  html: "Создана HTML-страница",
  audio: "Создано аудио",
  video: "Создано видео",
  text: "Создан текстовый файл",
  other: "Создано вложение",
};

const truncate = (value: string, max = 80): string =>
  value.length > max ? `${value.slice(0, max - 1)}…` : value;

const getStringArg = (args: Record<string, any>, keys: string[]): string => {
  for (const key of keys) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
};

const getFirstString = (value: unknown): string => {
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    const found = value.find((item) => typeof item === "string" && item.trim());
    return typeof found === "string" ? found.trim() : "";
  }
  return "";
};

const basename = (path: string): string => {
  const normalized = path.trim().replace(/\/+$/, "");
  return normalized.split("/").at(-1) || normalized;
};

const getFileToolName = (toolCall: ToolCall): string => {
  const args = (toolCall.args ?? {}) as Record<string, any>;
  const path =
    args.sandbox_path ?? args.file_path ?? args.path ?? args.filename ?? "";
  if (typeof path !== "string" || !path.trim()) return "";
  return truncate(basename(path), 80);
};

const getShellSummary = (toolCall: ToolCall): string => {
  const args = (toolCall.args ?? {}) as Record<string, any>;
  const description = getStringArg(args, ["description"]);
  if (description) return truncate(description, 80);

  const cmd =
    getFirstString(args.command) || getFirstString(args.commands) || "";
  const firstLine = cmd.split("\n")[0]?.trim() ?? "";
  return firstLine ? truncate(firstLine, 80) : "Командная строка";
};

export const getToolTitle = (toolCall: ToolCall): string => {
  const name = toolCall.name;
  const args = (toolCall.args ?? {}) as Record<string, any>;

  if (name === "shell") {
    return getShellSummary(toolCall);
  }

  if (name === "python") {
    const code = typeof args.code === "string" ? args.code : "";
    if (code) {
      const firstLine = code
        .split("\n")
        .map((l) => l.trim())
        .find((l) => l.length > 0);
      if (firstLine) return `Код-интерпретатор · ${truncate(firstLine, 70)}`;
    }
    return "Код-интерпретатор";
  }

  if (name in TOOL_MAP) {
    // @ts-ignore
    return TOOL_MAP[name] as string;
  }

  return name;
};

type ToolDisplay = {
  label: string;
  detail?: string;
};

const TOOL_LABELS: Record<string, string> = {
  await_shell: "Ожидает shell",
  open_port: "Открыл порт",
  delete_file: "Удалил",
  search: "Ищет в сети",
  get_urls: "Читает ссылки",
  get_documents: "Ищет в базе знаний",
  search_memories: "Ищет в памяти",
  read_skill_manifest: "Читает навык",
  analyze_image: "Анализирует изображение",
  gen_image: "Создаёт изображение",
  weather: "Проверяет погоду",
  get_workflow_runs: "Получает CI runs",
  list_pull_requests: "Получает pull requests",
  get_pull_request: "Получает pull request",
  vk_get_posts: "Получает посты VK",
  vk_get_comments: "Получает комментарии VK",
  vk_get_last_comments: "Получает последние комментарии VK",
  run_deep_research: "Глубокое исследование",
  researcher_agent: "Исследует",
  city_explore: "Исследует город",
  lean_canvas: "Создаёт Lean Canvas",
  create_landing: "Создаёт страницу",
  generate_presentation: "Создаёт презентацию",
  create_meme: "Создаёт мем",
  podcast_generate: "Создаёт подкаст",
  multi_tool_use: "Выполняет несколько действий",
  ask_questions: "Уточняющие вопросы",
};

const getHost = (url: string): string => {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
};

const getToolDisplay = (toolCall: ToolCall): ToolDisplay => {
  const name = toolCall.name;
  const args = (toolCall.args ?? {}) as Record<string, any>;

  if (name === "shell") {
    return { label: "Shell:", detail: getShellSummary(toolCall) };
  }

  if (name === "python") {
    const code = getStringArg(args, ["code"]);
    const firstLine = code
      .split("\n")
      .map((line) => line.trim())
      .find(Boolean);
    return {
      label: "Код-интерпретатор",
      detail: firstLine ? truncate(firstLine, 70) : undefined,
    };
  }

  if (name === "read_file") {
    return { label: "Прочитал", detail: getFileToolName(toolCall) };
  }
  if (name === "write_file") {
    return { label: "Создал", detail: getFileToolName(toolCall) };
  }
  if (name === "edit_file") {
    return { label: "Отредактировал", detail: getFileToolName(toolCall) };
  }
  if (name === "delete_file") {
    return { label: "Удалил", detail: getFileToolName(toolCall) };
  }

  if (name === "multi_tool_use") {
    const uses = Array.isArray(args.tool_uses) ? args.tool_uses.length : 0;
    return {
      label: TOOL_LABELS[name],
      detail: uses ? `${uses} действий` : undefined,
    };
  }

  if (name === "search") {
    const queries = Array.isArray(args.queries) ? args.queries : [];
    return {
      label: TOOL_LABELS[name],
      detail:
        queries.length > 1
          ? `${queries.length} запросов`
          : truncate(getFirstString(queries), 80),
    };
  }

  if (name === "get_urls") {
    const urls = Array.isArray(args.urls) ? args.urls : [];
    return {
      label: TOOL_LABELS[name],
      detail:
        urls.length > 1
          ? `${urls.length} ссылок`
          : truncate(getHost(getFirstString(urls)), 80),
    };
  }

  if (name === "get_workflow_runs" || name === "list_pull_requests") {
    const owner = getStringArg(args, ["owner"]);
    const repo = getStringArg(args, ["repo"]);
    return {
      label: TOOL_LABELS[name],
      detail: owner && repo ? `${owner}/${repo}` : undefined,
    };
  }

  if (name === "get_pull_request") {
    const owner = getStringArg(args, ["owner"]);
    const repo = getStringArg(args, ["repo"]);
    const pullNumber = args.pull_number ?? args.pullNumber;
    return {
      label: TOOL_LABELS[name],
      detail:
        owner && repo && pullNumber
          ? `${owner}/${repo}#${pullNumber}`
          : undefined,
    };
  }

  if (name === "podcast_generate") {
    const url = getStringArg(args, ["url"]);
    return { label: TOOL_LABELS[name], detail: url ? getHost(url) : undefined };
  }

  const detailByTool: Record<string, string> = {
    await_shell: getStringArg(args, ["shell_id", "pattern"]),
    open_port: args.port != null ? String(args.port) : "",
    get_documents: getStringArg(args, ["query"]),
    search_memories: getStringArg(args, ["query"]),
    read_skill_manifest: getStringArg(args, ["name"]),
    analyze_image: basename(getStringArg(args, ["image_path"])),
    gen_image: getStringArg(args, ["prompt"]),
    weather: getStringArg(args, ["city"]),
    vk_get_posts: getStringArg(args, ["domain", "owner_id"]),
    vk_get_comments: args.post_id != null ? String(args.post_id) : "",
    vk_get_last_comments: getStringArg(args, ["domain", "owner_id"]),
    run_deep_research: getStringArg(args, ["research_topic"]),
    researcher_agent: getStringArg(args, ["question"]),
    city_explore: getStringArg(args, ["city"]),
    lean_canvas: getStringArg(args, ["theme"]),
    create_landing: getStringArg(args, ["task"]),
    generate_presentation: getStringArg(args, ["presentation_task"]),
    create_meme: getStringArg(args, ["task"]),
  };

  const label = TOOL_LABELS[name] ?? getToolTitle(toolCall);
  const detail = detailByTool[name];
  return { label, detail: detail ? truncate(detail, 80) : undefined };
};

const EXT_LANG: Record<string, string> = {
  py: "python",
  js: "javascript",
  jsx: "jsx",
  mjs: "javascript",
  cjs: "javascript",
  ts: "typescript",
  tsx: "tsx",
  json: "json",
  html: "markup",
  htm: "markup",
  xml: "markup",
  svg: "markup",
  vue: "markup",
  css: "css",
  scss: "scss",
  sass: "sass",
  less: "less",
  md: "markdown",
  markdown: "markdown",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  yml: "yaml",
  yaml: "yaml",
  sql: "sql",
  java: "java",
  go: "go",
  rs: "rust",
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  hpp: "cpp",
  cs: "csharp",
  rb: "ruby",
  php: "php",
  kt: "kotlin",
  kts: "kotlin",
  swift: "swift",
  dart: "dart",
  r: "r",
  lua: "lua",
  pl: "perl",
  toml: "toml",
  ini: "ini",
  cfg: "ini",
  conf: "ini",
  env: "bash",
  dockerfile: "docker",
  txt: "text",
};

const getLanguageFromPath = (path: string): string => {
  const name = path.trim().split("/").at(-1)?.toLowerCase() ?? "";
  if (name === "dockerfile") return "docker";
  const ext = name.includes(".") ? (name.split(".").at(-1) ?? "") : "";
  return EXT_LANG[ext] ?? "text";
};

const codeStyle = {
  margin: 0,
  padding: "8px 10px",
  fontSize: "12px",
  borderRadius: 6,
  maxHeight: 400,
  overflow: "auto" as const,
};

type DiffLine = { type: "add" | "remove" | "context"; text: string };

const computeLineDiff = (before: string, after: string): DiffLine[] => {
  const a = before.split("\n");
  const b = after.split("\n");
  const m = a.length;
  const n = b.length;
  // LCS table, computed bottom-up.
  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    new Array<number>(n + 1).fill(0),
  );
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] =
        a[i] === b[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) {
      result.push({ type: "context", text: a[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      result.push({ type: "remove", text: a[i] });
      i++;
    } else {
      result.push({ type: "add", text: b[j] });
      j++;
    }
  }
  while (i < m) result.push({ type: "remove", text: a[i++] });
  while (j < n) result.push({ type: "add", text: b[j++] });
  return result;
};

const DIFF_STYLES = {
  add: { bg: "rgba(80, 250, 123, 0.16)", color: "#69ff94", sign: "+" },
  remove: { bg: "rgba(255, 85, 85, 0.16)", color: "#ff6e6e", sign: "-" },
  context: { bg: "transparent", color: "#f8f8f2", sign: " " },
} as const;

const DiffView: React.FC<{ before: string; after: string }> = ({
  before,
  after,
}) => {
  const lines = useMemo(() => computeLineDiff(before, after), [before, after]);
  return (
    <div
      className="overflow-auto rounded-md font-mono text-xs leading-5"
      style={{ maxHeight: 400, background: "#282a36", padding: "6px 0" }}
    >
      {lines.map((line, idx) => {
        const s = DIFF_STYLES[line.type];
        return (
          <div
            key={idx}
            style={{
              background: s.bg,
              color: s.color,
              padding: "0 10px",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            <span
              style={{ userSelect: "none", opacity: 0.5, marginRight: 8 }}
              aria-hidden
            >
              {s.sign}
            </span>
            {line.text.length ? line.text : " "}
          </div>
        );
      })}
    </div>
  );
};

const renderArgsBlock = (toolCall: ToolCall) => {
  if (toolCall.name === "write_file") {
    const args = (toolCall.args ?? {}) as Record<string, any>;
    const content = typeof args.content === "string" ? args.content : "";
    const path = typeof args.file_path === "string" ? args.file_path : "";
    return (
      <SyntaxHighlighter
        language={getLanguageFromPath(path)}
        style={dracula}
        customStyle={codeStyle}
        wrapLongLines
      >
        {content}
      </SyntaxHighlighter>
    );
  }

  if (toolCall.name === "edit_file") {
    const args = (toolCall.args ?? {}) as Record<string, any>;
    const findString =
      typeof args.find_string === "string" ? args.find_string : "";
    const replaceString =
      typeof args.replace_string === "string" ? args.replace_string : "";
    return <DiffView before={findString} after={replaceString} />;
  }

  if (toolCall.name === "python") {
    const code =
      typeof (toolCall.args as any)?.code === "string"
        ? ((toolCall.args as any).code as string)
        : JSON.stringify(toolCall.args ?? {}, null, 2);
    return (
      <SyntaxHighlighter
        language="python"
        style={dracula}
        customStyle={{
          margin: 0,
          padding: "8px 10px",
          fontSize: "12px",
          borderRadius: 6,
        }}
        wrapLongLines
      >
        {code}
      </SyntaxHighlighter>
    );
  }

  const pretty = JSON.stringify(toolCall.args ?? {}, null, 2);
  return (
    <SyntaxHighlighter
      language="json"
      style={dracula}
      customStyle={{
        margin: 0,
        padding: "8px 10px",
        fontSize: "12px",
        borderRadius: 6,
      }}
      wrapLongLines
    >
      {pretty}
    </SyntaxHighlighter>
  );
};

const renderResultBlock = (resultMessage: Message) => {
  const raw = resultMessage.content as string;
  let pretty = raw;
  try {
    pretty = JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    pretty = raw;
  }
  return (
    <SyntaxHighlighter
      language="json"
      style={dracula}
      customStyle={{
        margin: 0,
        padding: "8px 10px",
        fontSize: "12px",
        borderRadius: 6,
        maxHeight: 400,
        overflow: "auto",
      }}
      lineProps={{
        style: { wordBreak: "break-word", whiteSpace: "pre-wrap" },
      }}
      wrapLines
    >
      {pretty}
    </SyntaxHighlighter>
  );
};

interface ToolCallRowProps {
  toolCall: ToolCall;
  resultMessage?: Message;
  isStreaming: boolean;
  thread?: UseStream<GraphState>;
  onOpenAttachment: (att: any) => void;
}

const ToolCallRow: React.FC<ToolCallRowProps> = ({
  toolCall,
  resultMessage,
  isStreaming,
  thread,
  onOpenAttachment,
}) => {
  const [expanded, setExpanded] = useState(false);
  const hasResult = !!resultMessage;
  const isError = hasResult && (resultMessage as any)?.status === "error";
  const inFlight = isStreaming && !hasResult;
  // Остановлено пользователем: либо бэк уже вставил стаб с маркером, либо
  // вызов остался без результата после стопа (ран больше не стримится).
  // При активном interrupt вызов без результата ждёт approve, а не отменён.
  const isStopped = !!(resultMessage?.additional_kwargs as any)
    ?.stopped_by_user;
  const isCancelled =
    isStopped || (!hasResult && !inFlight && !thread?.interrupt);
  const toolDisplay = getToolDisplay(toolCall);

  const attachments: any[] =
    (resultMessage?.additional_kwargs?.tool_attachments as any[]) || [];

  const parsedPayload = useMemo(() => {
    if (!resultMessage) return null;
    try {
      return JSON.parse(resultMessage.content as string);
    } catch {
      return null;
    }
  }, [resultMessage]);

  const deepResearchPlan: DeepResearchSubQ[] | null = useMemo(() => {
    if (toolCall.name !== "run_deep_research") return null;
    // Финальный план из готового результата
    if (parsedPayload) {
      const inner = parsedPayload.data ?? parsedPayload;
      const plan = inner?.plan;
      if (Array.isArray(plan) && plan.length) return plan;
    }
    // Промежуточный план из UI-эвентов во время стрима
    if (inFlight && thread) {
      // @ts-ignore
      const uis = (thread.values?.ui ?? []).filter(
        (el: any) =>
          el.name === "agent_execution" &&
          el.props?.tool_call_id === toolCall.id,
      );
      let latest: DeepResearchSubQ[] | null = null;
      for (const u of uis) {
        // @ts-ignore
        const p = u.props?.plan;
        if (Array.isArray(p) && p.length) latest = p;
      }
      return latest;
    }
    return null;
  }, [toolCall.id, toolCall.name, parsedPayload, inFlight, thread]);

  const progressText: string | null = useMemo(() => {
    if (!inFlight || !thread) return null;
    // @ts-ignore
    const uis = (thread.values?.ui ?? []).filter(
      (el: any) =>
        el.name === "agent_execution" && el.props?.tool_call_id === toolCall.id,
    );
    if (!uis.length) return null;
    const last = uis.at(-1);
    if (last?.props?.node_text) return String(last.props.node_text);
    // @ts-ignore
    const agent = PROGRESS_AGENTS[toolCall.name];
    if (agent && last?.props?.node && agent[last.props.node]) {
      return agent[last.props.node];
    }
    return null;
  }, [inFlight, thread, toolCall.id, toolCall.name]);

  const progressImage: string | null = useMemo(() => {
    if (!inFlight || !thread) return null;
    // @ts-ignore
    const uis = (thread.values?.ui ?? []).filter(
      (el: any) =>
        el.name === "agent_execution" && el.props?.tool_call_id === toolCall.id,
    );
    const img = uis.at(-1)?.props?.image;
    return img || null;
  }, [inFlight, thread, toolCall.id]);

  const canExpand = true;

  return (
    <div className="flex flex-col">
      <button
        type="button"
        onClick={() => canExpand && setExpanded((v) => !v)}
        className="group flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-muted/40 cursor-pointer"
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center text-muted-foreground">
          {expanded ? <Minus size={14} /> : <Plus size={14} />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm text-foreground">
            {toolDisplay.label}
            {toolDisplay.detail && (
              <>
                {" "}
                <span className="text-muted-foreground">
                  {toolDisplay.detail}
                </span>
              </>
            )}
          </span>
          {progressText && (
            <span className="block truncate text-xs text-transparent bg-gradient-to-r from-muted-foreground/40 via-muted-foreground/70 to-muted-foreground/40 bg-clip-text animate-pulse">
              {progressText}
            </span>
          )}
        </span>
        <span className="ml-2 flex h-5 w-5 shrink-0 items-center justify-center">
          {inFlight ? (
            <Loader size={14} className="animate-spin text-muted-foreground" />
          ) : isCancelled ? (
            <Ban size={14} className="text-muted-foreground" />
          ) : isError ? (
            <X size={14} className="text-rose-500" />
          ) : hasResult ? (
            <Check size={14} className="text-emerald-500" />
          ) : null}
        </span>
      </button>

      {progressImage && (
        <div className="ml-7 mt-1">
          <img
            src={`data:image/png;base64,${progressImage}`}
            alt=""
            width={360}
            style={{ borderRadius: 4 }}
          />
        </div>
      )}

      {attachments.length > 0 && (
        <div className="ml-7 mt-1 flex flex-col gap-0.5">
          {attachments.map((att) => {
            const attachmentPath = att.sandbox_path ?? att.path;
            if (!attachmentPath) return null;
            const attachmentName =
              att.original_name ?? attachmentPath.split("/").at(-1);
            const label =
              ATTACHMENT_TEXTS[att.file_type ?? "image"] ??
              ATTACHMENT_TEXTS.other;
            return (
              <a
                key={attachmentPath}
                href=""
                onClick={(ev) => {
                  ev.preventDefault();
                  onOpenAttachment(att);
                }}
                className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
              >
                {label} · {attachmentName}
              </a>
            );
          })}
        </div>
      )}

      {expanded && (
        <div className="ml-7 mt-1.5 mb-1 flex flex-col gap-2">
          <div>
            <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
              параметры
            </div>
            {renderArgsBlock(toolCall)}
          </div>

          {hasResult && !isStopped && (
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                результат
              </div>
              {renderResultBlock(resultMessage!)}
            </div>
          )}

          {deepResearchPlan && <DeepResearchPlan plan={deepResearchPlan} />}
        </div>
      )}
    </div>
  );
};

interface ToolCallsListProps {
  toolCalls: ToolCall[];
  resultsById: Record<string, Message>;
  isStreaming: boolean;
  thread?: UseStream<GraphState>;
}

const ToolCallsList: React.FC<ToolCallsListProps> = ({
  toolCalls,
  resultsById,
  isStreaming,
  thread,
}) => {
  const [previewFile, setPreviewFile] = useState<any | null>(null);
  const notifiedDeepResearchIdsRef = useRef<Set<string>>(new Set());

  // response-widget-результаты (genui-виджеты, MCP-аппы, карточки планировщика)
  // рендерятся самостоятельными блоками ВНЕ рана (см. MessageList), поэтому не
  // показываем их строкой здесь — иначе виджет задублируется. ask_questions
  // тоже рисуется снаружи (live-форма при interrupt или "answered"-карточка).
  const visible = toolCalls.filter(
    (tc) =>
      tc.name !== "ask_questions" &&
      tc.name !== "write_todo" &&
      !isResponseWidget(tc.id ? resultsById[tc.id] : undefined),
  );

  useEffect(() => {
    for (const tc of visible) {
      if (tc.name !== "run_deep_research" || !tc.id) continue;
      const resultMessage = resultsById[tc.id];
      const resultId = resultMessage?.id ?? tc.id;
      if (!resultMessage || notifiedDeepResearchIdsRef.current.has(resultId)) {
        continue;
      }
      // Стаб «остановлено пользователем» — не повод слать нотификацию.
      if ((resultMessage.additional_kwargs as any)?.stopped_by_user) {
        notifiedDeepResearchIdsRef.current.add(resultId);
        continue;
      }
      notifiedDeepResearchIdsRef.current.add(resultId);
      notifyIfHidden(
        "Глубокое исследование завершено",
        "Отчёт готов — вернитесь во вкладку, чтобы посмотреть.",
      );
    }
  }, [resultsById, visible]);

  if (!visible.length) return null;

  return (
    <>
      <div className="flex flex-col gap-0.5">
        {visible.map((tc) => {
          const result = tc.id ? resultsById[tc.id] : undefined;
          // run_deep_research — особый кейс (глубоко завязан на стриминг).
          if (tc.name === "run_deep_research") {
            return (
              <DeepResearchToolCall
                key={tc.id ?? tc.name}
                toolCall={tc}
                resultMessage={tc.id ? resultsById[tc.id] : undefined}
                isStreaming={isStreaming}
                thread={thread}
                onOpenAttachment={setPreviewFile}
              />
            );
          }
          // Генеративная доска: композиция из результата (персистентно) или из
          // thread.values.ui (лайв во время стрима). Provider-agnostic.
          const composition =
            compositionFromResult(result) ?? compositionFor(thread, tc.id);
          if (composition) {
            return (
              <ComposedBoard key={tc.id ?? tc.name} composition={composition} />
            );
          }
          // GenUI-виджеты: по маркеру payload результата (provider-agnostic).
          const Widget = resolveWidget(result);
          if (Widget) {
            return (
              <Widget
                key={tc.id ?? tc.name}
                toolCall={tc}
                resultMessage={tc.id ? resultsById[tc.id] : undefined}
                isStreaming={isStreaming}
              />
            );
          }
          return (
            <ToolCallRow
              key={tc.id ?? tc.name}
              toolCall={tc}
              resultMessage={tc.id ? resultsById[tc.id] : undefined}
              isStreaming={isStreaming}
              thread={thread}
              onOpenAttachment={setPreviewFile}
            />
          );
        })}
      </div>

      <OverlayPortal
        isVisible={!!previewFile}
        onClose={() => setPreviewFile(null)}
      >
        <div className="bg-card rounded-lg p-2.5 w-full">
          {previewFile ? (
            <MessageAttachment
              path={previewFile.sandbox_path ?? previewFile.path}
              fileType={previewFile.file_type}
              alt={""}
              fullScreen={true}
            />
          ) : null}
        </div>
      </OverlayPortal>
    </>
  );
};

export default ToolCallsList;
