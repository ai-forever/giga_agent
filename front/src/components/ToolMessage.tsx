import React, { useEffect, useMemo, useRef, useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { dracula } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Message } from "@langchain/langgraph-sdk";
import Spinner from "./Spinner.tsx";
import { ChevronRight } from "lucide-react";
import OverlayPortal from "./OverlayPortal.tsx";
import { PROGRESS_AGENTS, TOOL_MAP } from "../config.ts";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "../interfaces.ts";
import MessageAttachment from "./attachments/MessageAttachment.tsx";
import { ToolCall } from "@langchain/core/messages/tool";
import { AIMessage } from "@langchain/langgraph-sdk";
import { notifyIfHidden } from "../lib/notifications.ts";

interface ToolMessageProps {
  message: Message;
  name: string;
}

interface ToolsExecProps {
  message: AIMessage;
  thread?: UseStream<GraphState>;
}

interface ToolExecProps {
  toolCall: ToolCall;
  thread?: UseStream<GraphState>;
}

interface AgentNode {
  text: string;
  image?: string;
}

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
  <div className="mt-3 flex flex-col gap-2">
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

export const ToolExecuting = ({ toolCall, thread }: ToolExecProps) => {
  const name = toolCall.name;
  const agentProgress: AgentNode | null = useMemo(() => {
    // @ts-ignore
    const uis = (thread.values.ui ?? []).filter(
      // @ts-ignore
      (el) =>
        el.name === "agent_execution" && el.props.tool_call_id === toolCall.id,
    );
    if (uis.length) {
      let image = uis.at(-1).props.image;
      let text;
      if (uis.at(-1).props.node_text) text = uis.at(-1).props.node_text;
      // @ts-ignore
      const agent = PROGRESS_AGENTS[name];
      if (agent) {
        text = agent[uis.at(-1).props.node];
      }
      if (text || image) {
        return {
          text,
          image,
        };
      }
      return null;
    }
    return null;
  }, [thread?.values.ui]);

  const deepResearchPlan: DeepResearchSubQ[] | null = useMemo(() => {
    if (name !== "run_deep_research") return null;
    // @ts-ignore
    const uis = (thread?.values?.ui ?? []).filter(
      // @ts-ignore
      (el) =>
        el.name === "agent_execution" && el.props.tool_call_id === toolCall.id,
    );
    let latest: DeepResearchSubQ[] | null = null;
    for (const u of uis) {
      // @ts-ignore
      const p = u.props?.plan;
      if (Array.isArray(p) && p.length) latest = p;
    }
    return latest;
  }, [thread?.values?.ui, name, toolCall.id]);
  // @ts-ignore
  const toolName = name in TOOL_MAP ? `: ${TOOL_MAP[name]} ` : "";
  const displayedRef = useRef<string>(""); // накапливаемый текст
  const [displayed, setDisplayed] = useState<string>("");
  const idxRef = useRef<number>(0);

  useEffect(() => {
    displayedRef.current = "";
    setDisplayed("");
    if (!agentProgress?.text) return;
    idxRef.current = 0;
    const words = agentProgress.text;
    let timer: NodeJS.Timeout;

    const step = () => {
      // случайный размер чанка: от 1 до 4 слов
      const chunkSize = Math.max(3, Math.floor(Math.random() * 6) + 1);
      const next = Math.min(idxRef.current + chunkSize, words.length);
      // добавляем words[idx..next]
      displayedRef.current =
        displayedRef.current + words.slice(idxRef.current, next);
      setDisplayed(displayedRef.current);
      idxRef.current = next;
      if (idxRef.current < words.length) {
        // случайная задержка: 20–120 мс
        const delay = 20 + Math.random() * 40;
        timer = setTimeout(step, delay);
      }
    };

    step();

    return () => clearTimeout(timer);
    // @ts-ignore
  }, [agentProgress?.text]);
  return (
    <div className="flex items-start mb-2 px-9">
      <div className="flex flex-col border border-2 border-border text-foreground p-4 rounded-lg flex-1 cursor-pointer max-w-full justify-center">
        <div className="flex items-center">
          <span className="text-sm ml-4">
            <span className="flex items-center">
              Инструмент выполняется{toolName} <Spinner size="12" />
            </span>
            {displayed && (
              <>
                <span className="text-transparent bg-gradient-to-r from-muted-foreground/40 via-muted-foreground/70 to-muted-foreground/40 bg-clip-text animate-pulse">
                  {displayed}
                </span>
              </>
            )}
            {agentProgress?.image && (
              <>
                <br />
                <img
                  style={{ marginTop: "10px", borderRadius: "4px" }}
                  src={`data:image/png;base64,${agentProgress.image}`}
                  width={400}
                />
              </>
            )}
          </span>
        </div>
        {deepResearchPlan && <DeepResearchPlan plan={deepResearchPlan} />}
      </div>
    </div>
  );
};

export const ToolsExecuting = ({ message, thread }: ToolsExecProps) => {
  if (
    thread?.interrupt ||
    // @ts-ignore
    !message.tool_calls
  ) {
    return null;
  }
  return message.tool_calls.map((el, index) => (
    <ToolExecuting toolCall={el} thread={thread} key={index} />
  ));
};

const ATTACHMENT_TEXTS = {
  plotly_graph: "В результате работы был сгенерирован график ",
  image: "В результате работы было сгенерировано изображение ",
  html: "В результате работы была сгенерирована HTML-страница",
  audio: "В результате работы было сгенерировано аудио",
  video: "В результате работы было сгенерировано видео",
  text: "В результате работы был сгенерирован текстовый файл ",
  other: "В результате работы было сгенерировано вложение ",
};

const ToolMessage: React.FC<ToolMessageProps> = ({ message, name }) => {
  const [expanded, setExpanded] = useState(false);
  const [file, setFile] = useState<any | null>(null);

  useEffect(() => {
    if (name === "run_deep_research") {
      notifyIfHidden(
        "Глубокое исследование завершено",
        "Отчёт готов — вернитесь во вкладку, чтобы посмотреть.",
      );
    }
    // namespaced по id сообщения — один mount per завершённый tool-call
  }, [name, (message as any)?.id]);

  if (message.type !== "tool") {
    return null;
  }

  const attachments: any = message.additional_kwargs?.tool_attachments || [];
  let content;
  let parsedPayload: any = null;
  try {
    const parsed = JSON.parse(message.content as string);
    parsedPayload = parsed;
    content = JSON.stringify(parsed, null, 2);
  } catch (e) {
    content = message.content as string;
  }

  const deepResearchFinalPlan: DeepResearchSubQ[] | null = (() => {
    if (name !== "run_deep_research" || !parsedPayload) return null;
    // Когда payload больше GIGA_AGENT_TOOL_MAX_SIZE, middleware оборачивает в
    // { data: <наш payload>, result_path, message } — см. tool_result.py.
    const inner = parsedPayload.data ?? parsedPayload;
    const plan = inner?.plan;
    return Array.isArray(plan) && plan.length ? plan : null;
  })();

  const handleLinkClick = (ev: React.MouseEvent, file: any) => {
    ev.preventDefault();
    setFile(file);
  };

  // @ts-ignore
  const toolName = name in TOOL_MAP ? `: ${TOOL_MAP[name]} ` : `: ${name}`;

  return (
    <>
      <div className="flex items-start mb-2 px-9">
        <div className="flex flex-col border border-2 cursor-pointer border-border text-foreground p-4 rounded-lg flex-1 cursor-pointer max-w-full">
          <div
            className="flex items-center"
            onClick={() => setExpanded((prev) => !prev)}
          >
            <span
              className="inline-block mr-2 transition-transform duration-200"
              style={{ transform: expanded ? "rotate(90deg)" : "rotate(0deg)" }}
            >
              <ChevronRight size={16} />
            </span>
            <span className="text-sm flex align-middle">
              Результат выполнения инструмента{toolName}
            </span>
          </div>

          <div
            className={[
              "overflow-auto cursor-text transition-[max-height] duration-700 print:hidden",
              expanded ? "max-h-[400px]" : "max-h-0",
            ].join(" ")}
          >
            <SyntaxHighlighter
              language="json"
              lineProps={{
                style: { wordBreak: "break-word", whiteSpace: "pre-wrap" },
              }}
              style={dracula}
              showLineNumbers
              wrapLines={true}
            >
              {content}
            </SyntaxHighlighter>
          </div>
          {deepResearchFinalPlan && (
            <DeepResearchPlan plan={deepResearchFinalPlan} />
          )}
        </div>
      </div>
      {attachments.length > 0 && (
        <div className="flex flex-col gap-3">
          {attachments.map((att: any) => {
            const attachmentPath = att["sandbox_path"] ?? att["path"];
            if (!attachmentPath) return null;
            const attachmentName =
              att["original_name"] ?? attachmentPath.split("/").at(-1);
            return (
              <a
                key={attachmentPath}
                href=""
                onClick={(ev) => handleLinkClick(ev, att)}
                className="px-9 ml-3 text-foreground text-xs underline"
              >
                {
                  // @ts-ignore
                  ATTACHMENT_TEXTS[att["file_type"] ?? "image/png"]
                }{" "}
                {attachmentName}
              </a>
            );
          })}
        </div>
      )}
      <OverlayPortal isVisible={!!file} onClose={() => setFile(null)}>
        <div className="bg-card rounded-lg p-2.5">
          {file ? (
            <MessageAttachment
              path={file["sandbox_path"] ?? file["path"]}
              fileType={file["file_type"]}
              alt={""}
              fullScreen={true}
            />
          ) : (
            <></>
          )}
        </div>
      </OverlayPortal>
    </>
  );
};

export default ToolMessage;
