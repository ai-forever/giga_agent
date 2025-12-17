import React, { useEffect, useMemo, useRef, useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { dracula } from "react-syntax-highlighter/dist/cjs/styles/prism";
import { Message } from "@langchain/langgraph-sdk";
import Spinner from "./Spinner.tsx";
import { ChevronRight } from "lucide-react";
import OverlayPortal from "./OverlayPortal.tsx";
import { PROGRESS_AGENTS, TOOL_MAP } from "../config.ts";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "../interfaces.ts";
import MessageAttachment from "./attachments/MessageAttachment.tsx";

interface ToolMessageProps {
  message: Message;
  name: string;
}

interface ToolExecProps {
  messages: Message[];
  thread?: UseStream<GraphState>;
}

interface AgentNode {
  text: string;
  image?: string;
}

export const ToolExecuting = ({ messages, thread }: ToolExecProps) => {
  // @ts-ignore
  const name = messages[messages.length - 1]?.tool_calls?.length
    ? // @ts-ignore
      messages[messages.length - 1]?.tool_calls[0].name
    : "none";
  const agentProgress: AgentNode | null = useMemo(() => {
    // @ts-ignore
    const uis = (thread.values.ui ?? []).filter(
      // @ts-ignore
      (el) => el.name === "agent_execution",
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
  }, [agentProgress]);
  if (
    thread?.interrupt ||
    !messages ||
    // @ts-ignore
    !messages[messages.length - 1]?.tool_calls?.length
  ) {
    return null;
  }
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
      </div>
    </div>
  );
};

const ATTACHMENT_TEXTS = {
  plotly_graph: "В результате работы был сгенерирован график ",
  image: "В результате работы было сгенерировано изображение ",
  html: "В результате работы была сгенерирована HTML-страница",
  audio: "В результате работы было сгенерировано аудио",
  text: "В результате работы был сгенерирован текстовый файл ",
  other: "В результате работы было сгенерировано вложение ",
};

const ToolMessage: React.FC<ToolMessageProps> = ({ message, name }) => {
  const [expanded, setExpanded] = useState(false);
  const [file, setFile] = useState<any | null>(null);

  if (message.type !== "tool") {
    return null;
  }

  const attachments: any = message.additional_kwargs?.tool_attachments || [];
  let content;
  try {
    content = JSON.stringify(JSON.parse(message.content as string), null, 2);
  } catch (e) {
    content = message.content as string;
  }

  const handleLinkClick = (ev: React.MouseEvent, file: any) => {
    ev.preventDefault();
    setFile(file);
  };

  // @ts-ignore
  const toolName = name in TOOL_MAP ? `: ${TOOL_MAP[name]} ` : "";

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
        </div>
      </div>
      {attachments.length > 0 && (
        <div className="flex flex-col gap-3">
          {attachments.map((att: any) => {
            return (
              <a
                key={att["path"]}
                href=""
                onClick={(ev) => handleLinkClick(ev, att)}
                className="px-9 ml-3 text-foreground text-xs underline"
              >
                {
                  // @ts-ignore
                  ATTACHMENT_TEXTS[att["file_type"] ?? "image/png"]
                }{" "}
                {att["path"].split("/").at(-1)}
              </a>
            );
          })}
        </div>
      )}
      <OverlayPortal isVisible={!!file} onClose={() => setFile(null)}>
        <div className="bg-card rounded-lg p-2.5">
          {file ? (
            <MessageAttachment path={file["path"]} alt={""} fullScreen={true} />
          ) : (
            <></>
          )}
        </div>
      </OverlayPortal>
    </>
  );
};

export default ToolMessage;
