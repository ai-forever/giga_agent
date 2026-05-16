import React from "react";
import styled from "styled-components";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { dracula } from "react-syntax-highlighter/dist/esm/styles/prism";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeRaw from "rehype-raw";
import Markdown from "react-markdown";
import MessageAttachment from "./MessageAttachment.tsx";
import { cn } from "@/lib/utils.ts";
import rehypeKatex from "@/lib/rehype_katex.ts";
import {
  buildContentByPathUrl,
  inferAttachmentTypeFromPath,
  isInlineMarkdownAttachmentPath,
} from "./file-utils.ts";
import Text from "./Text.tsx";
import MermaidDiagram, { MermaidStreamingContext } from "./MermaidDiagram.tsx";
import {
  CitationsProvider,
  parseSources,
  remarkSources,
  SourcesList,
  transformCitationsInChildren,
} from "@/components/deep_research/citations";

// Оборачивает ссылки/картинки вида ](attachment:...) с пробелами или скобками в <...>,
// чтобы CommonMark корректно парсил URI без URL-энкода.
// Ручной парсер, а не regex, т.к. скобки внутри URL ломают regex-подход.
const wrapFilesLinksWithAngles = (
  markdown: string | null | undefined,
): string => {
  if (!markdown) return "";

  const ATTACHMENT_PREFIX = "attachment:";
  let result = "";
  let i = 0;

  while (i < markdown.length) {
    // Ищем начало ссылки: "![" или "["
    const bangBracket = markdown.indexOf("![", i);
    const bracket = markdown.indexOf("[", i);

    let linkStart: number;
    if (bangBracket === -1 && bracket === -1) {
      result += markdown.slice(i);
      break;
    } else if (bangBracket === -1) {
      linkStart = bracket;
    } else if (bracket === -1) {
      linkStart = bangBracket;
    } else {
      linkStart = Math.min(bangBracket, bracket);
    }

    result += markdown.slice(i, linkStart);

    const prefixStart = linkStart;
    // Пропускаем "!" если есть
    let pos = markdown[linkStart] === "!" ? linkStart + 1 : linkStart;
    if (markdown[pos] !== "[") {
      result += markdown[linkStart];
      i = linkStart + 1;
      continue;
    }
    pos++; // после "["

    // Ищем закрывающую "]"
    let depth = 1;
    while (pos < markdown.length && depth > 0) {
      if (markdown[pos] === "[") depth++;
      else if (markdown[pos] === "]") depth--;
      if (depth > 0) pos++;
    }
    if (depth !== 0 || pos >= markdown.length) {
      result += markdown[linkStart];
      i = linkStart + 1;
      continue;
    }
    pos++; // после "]"

    // Ожидаем "("
    if (pos >= markdown.length || markdown[pos] !== "(") {
      result += markdown.slice(linkStart, pos);
      i = pos;
      continue;
    }
    pos++; // после "("

    // Проверяем, начинается ли URL с "attachment:" (возможно с "<")
    const alreadyAngled = markdown[pos] === "<";
    const urlCheckStart = alreadyAngled ? pos + 1 : pos;
    if (!markdown.slice(urlCheckStart).startsWith(ATTACHMENT_PREFIX)) {
      result += markdown.slice(linkStart, pos);
      i = pos;
      continue;
    }

    if (alreadyAngled) {
      // Уже обёрнуто в <>, не трогаем — ищем >)
      const closeAngle = markdown.indexOf(">)", pos);
      if (closeAngle === -1) {
        result += markdown.slice(linkStart, pos);
        i = pos;
        continue;
      }
      result += markdown.slice(linkStart, closeAngle + 2);
      i = closeAngle + 2;
      continue;
    }

    // Извлекаем URL со сбалансированными скобками
    let parenDepth = 1;
    let urlEnd = pos;
    while (urlEnd < markdown.length && parenDepth > 0) {
      if (markdown[urlEnd] === "(") parenDepth++;
      else if (markdown[urlEnd] === ")") parenDepth--;
      if (parenDepth > 0) urlEnd++;
    }
    if (parenDepth !== 0) {
      result += markdown.slice(linkStart, pos);
      i = pos;
      continue;
    }

    const url = markdown.slice(pos, urlEnd);
    const prefix = markdown.slice(prefixStart, pos); // "![alt](" или "[text]("

    if (url.includes(" ") || url.includes("(") || url.includes(")")) {
      result += `${prefix}<${url}>)`;
    } else {
      result += `${prefix}${url})`;
    }
    i = urlEnd + 1; // после финальной ")"
  }

  return result;
};

const getYouTubeId = (url: string): string | null => {
  const regExp =
    /^.*(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([^#&?]{11}).*/;
  const match = url.match(regExp);
  return match ? match[1] : null;
};

// RuTube ID: https://rutube.ru/video/<id>/
const getRutubeId = (url: string): string | null => {
  const regExp = /rutube\.ru\/video\/([0-9a-fA-F]{32})/;
  const match = url.match(regExp);
  return match ? match[1] : null;
};

// отзывчивый контейнер для видео 16:9
const VideoWrapper = styled.div`
  position: relative;
  width: 100%;
  padding-bottom: 56.25%; /* 16:9 */
  margin: 8px 0;

  iframe {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
  }
`;

const buildMarkdownComponents = (transformText: boolean) => {
  const maybeTransform = (children: React.ReactNode): React.ReactNode =>
    transformText ? transformCitationsInChildren(children) : children;

  return {
    h1: ({ className, children, ...props }: any) => (
      <h1
        className={cn(
          "mb-8 scroll-m-20 text-4xl font-extrabold tracking-tight last:mb-0",
          className,
        )}
        {...props}
      >
        {maybeTransform(children)}
      </h1>
    ),

    h2: ({ className, children, ...props }: any) => (
      <h2
        className={cn(
          "mt-8 mb-4 scroll-m-20 text-3xl font-semibold tracking-tight first:mt-0 last:mb-0",
          className,
        )}
        {...props}
      >
        {maybeTransform(children)}
      </h2>
    ),
    h3: ({ className, children, ...props }: any) => (
      <h3
        className={cn(
          "mt-6 mb-4 scroll-m-20 text-2xl font-semibold tracking-tight first:mt-0 last:mb-0",
          className,
        )}
        {...props}
      >
        {maybeTransform(children)}
      </h3>
    ),
    h4: ({ className, children, ...props }: any) => (
      <h4
        className={cn(
          "mt-6 mb-4 scroll-m-20 text-xl font-semibold tracking-tight first:mt-0 last:mb-0",
          className,
        )}
        {...props}
      >
        {maybeTransform(children)}
      </h4>
    ),
    h5: ({ className, children, ...props }: any) => (
      <h5
        className={cn(
          "my-4 text-lg font-semibold first:mt-0 last:mb-0",
          className,
        )}
        {...props}
      >
        {maybeTransform(children)}
      </h5>
    ),
    h6: ({ className, children, ...props }: any) => (
      <h6
        className={cn("my-4 font-semibold first:mt-0 last:mb-0", className)}
        {...props}
      >
        {maybeTransform(children)}
      </h6>
    ),
    p: ({ className, children, ...props }: any) => (
      <div
        className={cn("leading-7 first:mt-0 last:mb-0", className)}
        {...props}
      >
        {maybeTransform(children)}
      </div>
    ),
    li: ({ className, children, ...props }: any) => (
      <li className={className} {...props}>
        {maybeTransform(children)}
      </li>
    ),
    blockquote: ({ className, children, ...props }: any) => (
      <blockquote
        className={cn("border-l-2 pl-6 italic", className)}
        {...props}
      >
        {maybeTransform(children)}
      </blockquote>
    ),
    ul: ({ className, ...props }: { className?: string }) => (
      <ul
        className={cn("my-5 ml-6 list-disc [&>li]:mt-2", className)}
        {...props}
      />
    ),
    ol: ({ className, ...props }: { className?: string }) => (
      <ol
        className={cn("my-4 ml-6 list-decimal [&>li]:mt-2", className)}
        {...props}
      />
    ),
    hr: ({ className, ...props }: { className?: string }) => (
      <hr className={cn("my-5 border-b", className)} {...props} />
    ),
    table: ({ className, ...props }: { className?: string }) => (
      <table
        className={cn(
          "my-5 w-full border-separate border-spacing-0 overflow-y-auto",
          className,
        )}
        {...props}
      />
    ),
    th: ({ className, ...props }: { className?: string }) => (
      <th
        className={cn(
          "bg-muted px-4 py-2 text-left font-bold first:rounded-tl-lg last:rounded-tr-lg [&[align=center]]:text-center [&[align=right]]:text-right",
          className,
        )}
        {...props}
      />
    ),
    td: ({ className, ...props }: { className?: string }) => (
      <td
        className={cn(
          "border-b border-l px-4 py-2 text-left last:border-r [&[align=center]]:text-center [&[align=right]]:text-right",
          className,
        )}
        {...props}
      />
    ),
    tr: ({ className, ...props }: { className?: string }) => (
      <tr
        className={cn(
          "m-0 border-b p-0 first:border-t [&:last-child>td:first-child]:rounded-bl-lg [&:last-child>td:last-child]:rounded-br-lg",
          className,
        )}
        {...props}
      />
    ),
    sup: ({ className, ...props }: { className?: string }) => (
      <sup
        className={cn("[&>a]:text-xs [&>a]:no-underline", className)}
        {...props}
      />
    ),
    code({ node, inline, className, children, ...props }: any) {
      // если это инлайновый <code>, оставляем как есть:

      if (inline) {
        return (
          <code className={className} {...props}>
            {children}
          </code>
        );
      }
      const content = String(children);
      const match = /language-(\w+)/.exec(className || "");

      // Mermaid-диаграммы рендерим через mermaid.js
      if (match?.[1] === "mermaid") {
        return <MermaidDiagram chart={content.replace(/\n$/, "")} />;
      }

      // для всех блочных кодов — всегда SyntaxHighlighter
      const additionalStyles: React.CSSProperties = {
        padding: "0.2em 0.5em",
        display: "inline-flex",
        maxWidth: "100%",
      };
      return (
        <SyntaxHighlighter
          style={dracula}
          customStyle={content.includes("\n") ? {} : additionalStyles}
          PreTag={content.includes("\n") ? "div" : "span"}
          // если язык не указан — просто передаём undefined или пустую строку
          language={match?.[1] ?? undefined}
          {...props}
        >
          {content.replace(/\n$/, "")}
        </SyntaxHighlighter>
      );
    },

    a({ href, children, ...props }: any) {
      if (!href) return <a {...props}>{children}</a>;

      if (href.startsWith("attachment:")) {
        const path = decodeURI(href.replace(/^attachment:/, ""));
        const fileType = inferAttachmentTypeFromPath(path);
        if (
          fileType === "image" ||
          fileType === "audio" ||
          fileType === "video"
        ) {
          return <MessageAttachment path={path} fileType={fileType} />;
        }
        if (fileType === "text" && isInlineMarkdownAttachmentPath(path)) {
          const fileLabel = path.split("/").filter(Boolean).pop() || "file";
          return <Text id={fileLabel} path={path} />;
        }
        return (
          <a
            href={buildContentByPathUrl(path)}
            target="_blank"
            rel="noopener noreferrer"
            {...props}
          >
            {children}
          </a>
        );
      }

      // YouTube
      const ytId = getYouTubeId(href);
      if (ytId) {
        const embedUrl = `https://www.youtube.com/embed/${ytId}`;
        return (
          <VideoWrapper>
            <iframe
              src={embedUrl}
              frameBorder="0"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
              title="YouTube video"
            />
          </VideoWrapper>
        );
      }

      // RuTube
      const rtId = getRutubeId(href);
      if (rtId) {
        const embedUrl = `https://rutube.ru/play/embed/${rtId}/`;
        return (
          <VideoWrapper>
            <iframe
              src={embedUrl}
              frameBorder="0"
              allow="clipboard-write; autoplay"
              allowFullScreen
              title="RuTube video"
            />
          </VideoWrapper>
        );
      }

      if (href.startsWith("file:")) {
        const filePath = decodeURI(href.replace(/^file:\/?/, ""));
        return (
          <a
            href={buildContentByPathUrl(filePath)}
            target="_blank"
            rel="noopener noreferrer"
            {...props}
          >
            {children}
          </a>
        );
      }

      // остальные ссылки
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
          {children}
        </a>
      );
    },
    "sources-list": () => <SourcesList />,
    img({ src, alt, ...props }: any) {
      if (!src) return null;
      if (src.startsWith("attachment:")) {
        const path = decodeURI(src.replace(/^attachment:/, ""));
        return <MessageAttachment path={path} alt={alt} />;
      }
      // if (src.startsWith("graph:")) {
      //   const graphId = src.replace(/^graph:/, "");
      //   return <GraphImage id={graphId} alt={alt} />;
      // }
      // if (src.startsWith("html:")) {
      //   const graphId = src.replace(/^html:/, "");
      //   return (
      //     <div style={{ marginTop: "15px" }}>
      //       <HTMLPage id={graphId} alt={alt} />
      //     </div>
      //   );
      // }
      // if (src.startsWith("audio:")) {
      //   const audioId = src.replace(/^audio:/, "");
      //   return <AudioPlayer id={audioId} alt={alt} />;
      // }
      if (src.startsWith("file:")) {
        const filePath = decodeURI(src.replace(/^file:\/?/, ""));
        return (
          <a
            href={buildContentByPathUrl(filePath)}
            rel={"noopener noreferrer"}
            target={"_blank"}
          >
            {alt}
          </a>
        );
      }
      // Обычное изображение
      return (
        <img
          style={{
            maxWidth: "300px",
            width: "100%",
            borderRadius: "8px",
            padding: "4px 0",
            display: "block",
          }}
          src={src}
          alt={alt}
          {...props}
          onError={(event) => {
            // @ts-ignore
            event.target.style.display = "none";
          }}
        />
      );
    },
  };
};

const defaultMarkdownComponents = buildMarkdownComponents(false);
const citationMarkdownComponents = buildMarkdownComponents(true);

interface TextMarkdownProps {
  children: string | null | undefined;
  isStreaming?: boolean;
}

const TextMarkdown: React.FC<TextMarkdownProps> = (props) => {
  const sources = React.useMemo(
    () => parseSources(props.children),
    [props.children],
  );
  const hasSources = sources.size > 0;
  const components = hasSources
    ? citationMarkdownComponents
    : defaultMarkdownComponents;

  const remarkPlugins: any[] = [
    remarkGfm,
    [remarkMath, { singleDollarTextMath: true }],
  ];
  if (hasSources) remarkPlugins.push(remarkSources);

  const markdown = (
    <MermaidStreamingContext.Provider value={props.isStreaming ?? false}>
      <Markdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={[[rehypeKatex, { output: "mathml" }], rehypeRaw]}
        urlTransform={(uri) => uri}
        components={components}
      >
        {wrapFilesLinksWithAngles(props.children)}
      </Markdown>
    </MermaidStreamingContext.Provider>
  );

  if (!hasSources) return markdown;

  return <CitationsProvider sources={sources}>{markdown}</CitationsProvider>;
};

export default TextMarkdown;
