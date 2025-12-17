import React from "react";
import styled from "styled-components";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { dracula } from "react-syntax-highlighter/dist/cjs/styles/prism";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeRaw from "rehype-raw";
import Markdown from "react-markdown";
import MessageAttachment from "./MessageAttachment.tsx";
import { cn } from "@/lib/utils.ts";
import rehypeKatex from "@/lib/rehype_katex.ts";

// Оборачивает ссылки/картинки вида ](/files/...) и ](attachment:/files/...) с пробелами в <...>,
// чтобы CommonMark корректно парсил URI без URL-энкода.
const wrapFilesLinksWithAngles = (
  markdown: string | null | undefined,
): string => {
  if (!markdown) return "";
  return markdown.replace(
    /(!?\[[^\]]*\]\()(<)?((?:attachment:)[^)\n]*?)(>)?\)/g,
    (match, prefix: string, hasLt: string, url: string, hasRt: string) => {
      if (hasLt || hasRt) return match;
      if (url.includes(" ")) {
        return `${prefix}<${url}>)`;
      }
      return match;
    },
  );
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

const markdownComponents = {
  h1: ({ className, ...props }: { className?: string }) => (
    <h1
      className={cn(
        "mb-8 scroll-m-20 text-4xl font-extrabold tracking-tight last:mb-0",
        className,
      )}
      {...props}
    />
  ),

  h2: ({ className, ...props }: { className?: string }) => (
    <h2
      className={cn(
        "mt-8 mb-4 scroll-m-20 text-3xl font-semibold tracking-tight first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h3: ({ className, ...props }: { className?: string }) => (
    <h3
      className={cn(
        "mt-6 mb-4 scroll-m-20 text-2xl font-semibold tracking-tight first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h4: ({ className, ...props }: { className?: string }) => (
    <h4
      className={cn(
        "mt-6 mb-4 scroll-m-20 text-xl font-semibold tracking-tight first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h5: ({ className, ...props }: { className?: string }) => (
    <h5
      className={cn(
        "my-4 text-lg font-semibold first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h6: ({ className, ...props }: { className?: string }) => (
    <h6
      className={cn("my-4 font-semibold first:mt-0 last:mb-0", className)}
      {...props}
    />
  ),
  p: ({ className, ...props }: { className?: string }) => (
    <div
      className={cn("leading-7 first:mt-0 last:mb-0", className)}
      {...props}
    />
  ),
  blockquote: ({ className, ...props }: { className?: string }) => (
    <blockquote
      className={cn("border-l-2 pl-6 italic", className)}
      {...props}
    />
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
    // для всех блочных кодов — всегда SyntaxHighlighter
    const match = /language-(\w+)/.exec(className || "");
    const additionalStyles: React.CSSProperties = {
      padding: "0.2em 0.5em",
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
      const filePath = href.replace(/^file:\/?/, "");
      return (
        <a
          href={`/files/${filePath}`}
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
  img({ src, alt, ...props }: any) {
    if (!src) return null;
    if (src.startsWith("attachment:")) {
      const path = src.replace(/^attachment:/, "");
      return <MessageAttachment path={decodeURI(path)} alt={alt} />;
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
      const filePath = src.replace(/^file:\/?/, "");
      return (
        <a
          href={`/files/${filePath}`}
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

interface TextMarkdownProps {
  children: string | null | undefined;
}

const TextMarkdown: React.FC<TextMarkdownProps> = (props) => {
  return (
    <Markdown
      remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: true }]]}
      rehypePlugins={[[rehypeKatex, { output: "mathml" }], rehypeRaw]}
      urlTransform={(uri) => uri}
      components={markdownComponents}
    >
      {wrapFilesLinksWithAngles(props.children)}
    </Markdown>
  );
};

export default TextMarkdown;
