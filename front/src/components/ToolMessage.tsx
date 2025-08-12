import React, { useEffect, useRef, useState } from "react";
import styled, { keyframes } from "styled-components";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { dracula } from "react-syntax-highlighter/dist/cjs/styles/prism";
import { Message } from "@langchain/langgraph-sdk";
import Spinner from "./Spinner.tsx";
import { ChevronRight } from "lucide-react";
import OverlayPortal from "./OverlayPortal.tsx";
import GraphImage from "./GraphImage.tsx";
import HTMLPage from "./HTMLPage.tsx";
import { TOOL_MAP } from "../config.ts";
import AudioPlayer from "./AudioPlayer.tsx";
// @ts-ignore
import { UseStream } from "@langchain/langgraph-sdk/dist/react/stream";
import { GraphState } from "../interfaces.ts";

const ToolMessageContainer = styled.div`
  display: flex;
  align-items: flex-start;
  margin-bottom: 16px;
  padding: 12px 36px;
`;

const Bubble = styled.div`
  display: flex;
  flex-direction: column;
  border: 1px solid gray;
  color: #fff;
  padding: 16px 16px;
  border-radius: 8px;
  flex: 1;
  cursor: pointer;
  max-width: 100%;
  //min-height: 50px;
  justify-content: center;
`;

const Header = styled.div`
  display: flex;
  align-items: center;
`;

const ExpandIcon = styled.span<{ expanded: boolean }>`
  display: inline-block;
  margin-right: 8px;
  transition: transform 0.2s ease;
  transform: rotate(${(props) => (props.expanded ? "90deg" : "0deg")});
  font-weight: bold;
`;

const CollapsedText = styled.span`
  font-size: 14px;
`;

const CodeContainer = styled.div<{ expanded: boolean }>`
  display: ${(props) => (props.expanded ? "block" : "none")};
  margin-top: 8px;
  overflow: auto;
  cursor: text;
  max-height: ${(props) => (props.expanded ? "400px" : "0")};
  transition: max-height 0.6s;
  @media print {
    display: none;
  }
`;

const AttachmentsContainer = styled.div`
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
`;

const AttachmentLink = styled.a`
  padding: 0 36px;
  margin-left: 12px;
  color: white;
  font-size: 12px;
`;

const OverlayBox = styled.div`
  background-color: #1f1f1f;
  border-radius: 8px;
  padding: 10px;
`;

// Анимация перемещения фона слева направо
const shimmer = keyframes`
  0% { background-position: -100% 0; }
  100% { background-position: 200% 0; }
`;

// Анимация плавного появления
const fadeIn = keyframes`
  from { opacity: 0; }
  to { opacity: 1; }
`;

const ToolProgress = styled.span`
  color: transparent;
  background: linear-gradient(
    90deg,
    rgba(200, 200, 200, 0.4) 0%,
    rgba(200, 200, 200, 0.6) 50%,
    rgba(200, 200, 200, 0.4) 100%
  ); // вертикальная светлая линия
  background-size: 50% 100%;
  background-repeat: repeat;
  background-position: -100% 0;
  background-clip: text;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;

  animation:
    ${fadeIn} 0.5s ease-out,
    ${shimmer} 3.5s linear infinite;
`;

interface ToolMessageProps {
  message: Message;
  name: string;
}

interface ToolExecProps {
  progressSubstring?: string;
  messages: Message[];
  thread?: UseStream<GraphState>;
}

export const ToolExecuting = ({
  progressSubstring,
  messages,
  thread,
}: ToolExecProps) => {
  // @ts-ignore
  const name = messages[messages.length - 1]?.tool_calls?.length
    ? // @ts-ignore
      messages[messages.length - 1]?.tool_calls[0].name
    : "none";
  // @ts-ignore
  const toolName = name in TOOL_MAP ? `: ${TOOL_MAP[name]} ` : "";
  const displayedRef = useRef<string>(""); // накапливаемый текст
  const [displayed, setDisplayed] = useState<string>("");
  const idxRef = useRef<number>(0);

  useEffect(() => {
    if (!progressSubstring) return;
    displayedRef.current = "";
    setDisplayed("");
    idxRef.current = 0;
    const words = progressSubstring;
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
  }, [progressSubstring]);
  if (
    thread?.interrupt ||
    !messages ||
    // @ts-ignore
    !messages[messages.length - 1]?.tool_calls?.length
  ) {
    return null;
  }
  return (
    <ToolMessageContainer>
      <Bubble>
        <Header>
          <CollapsedText style={{ marginLeft: "16px" }}>
            Инструмент выполняется{toolName} <Spinner />
            {progressSubstring && (
              <>
                <br />
                <ToolProgress>{displayed}</ToolProgress>
              </>
            )}
          </CollapsedText>
        </Header>
      </Bubble>
    </ToolMessageContainer>
  );
};

const ATTACHMENT_TEXTS = {
  "application/vnd.plotly.v1+json":
    "В результате работы был сгенерирован график ",
  "image/png": "В результате работы было сгенерировано изображение ",
  "text/html": "В результате работы была сгенерирована HTML-страница",
  "audio/mp3": "В результате работы было сгенерировано аудио",
};

const ToolMessage: React.FC<ToolMessageProps> = ({ message, name }) => {
  const [expanded, setExpanded] = useState(false);
  const [file, setFile] = useState<any | null>(null);

  if (message.type !== "tool") {
    return null;
  }

  const attachments: any = message.additional_kwargs?.tool_attachments || [];
  let content = null;
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
      <ToolMessageContainer>
        <Bubble>
          <Header onClick={() => setExpanded((prev) => !prev)}>
            <ExpandIcon expanded={expanded}>
              <ChevronRight size={16} />
            </ExpandIcon>
            <CollapsedText>
              Результат выполнения инструмента{toolName}
            </CollapsedText>
          </Header>

          <CodeContainer expanded={expanded}>
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
          </CodeContainer>
        </Bubble>
      </ToolMessageContainer>
      {attachments.length > 0 && (
        <AttachmentsContainer>
          {attachments.map((att: any) => {
            return (
              <AttachmentLink
                key={att["file_id"]}
                href=""
                onClick={(ev) => handleLinkClick(ev, att)}
              >
                {
                  // @ts-ignore
                  ATTACHMENT_TEXTS[att["type"] ?? "image/png"]
                }{" "}
                {att["file_id"]}
              </AttachmentLink>
            );
          })}
        </AttachmentsContainer>
      )}
      <OverlayPortal isVisible={!!file} onClose={() => setFile(null)}>
        <OverlayBox>
          {file ? (
            <>
              {file["type"] === "text/html" ? (
                <HTMLPage id={file["file_id"]} fullScreen={true} />
              ) : (
                <>
                  {file["type"] === "audio/mp3" ? (
                    <AudioPlayer id={file["file_id"]} />
                  ) : (
                    <GraphImage id={file["file_id"]} />
                  )}
                </>
              )}
            </>
          ) : (
            <></>
          )}
        </OverlayBox>
      </OverlayPortal>
    </>
  );
};

export default ToolMessage;
