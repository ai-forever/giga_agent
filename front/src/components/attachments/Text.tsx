import React, { useEffect, useRef, useState } from "react";
import { ChevronUp } from "lucide-react";
import TextMarkdown from "./TextMarkdown.tsx";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api-client.ts";
import {
  buildContentByPathPreviewUrl,
  buildContentByPathUrl,
} from "./file-utils.ts";

interface TextProps {
  id: string;
  alt?: string;
  path: string;
}

const Text: React.FC<TextProps> = ({ id, path }) => {
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [expanded, setExpanded] = useState<boolean>(false);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const COLLAPSED_MAX = 320;
  const [maxHeight, setMaxHeight] = useState<number>(COLLAPSED_MAX);
  const [showFade, setShowFade] = useState<boolean>(true);
  const fadeMask =
    "linear-gradient(to bottom, rgba(0,0,0,1) 70%, rgba(0,0,0,0) 100%)";

  useEffect(() => {
    let cancelled = false;
    const loadText = async () => {
      try {
        const raw = await apiClient.getTextWithRedirectInstruction(
          buildContentByPathPreviewUrl(path),
          {
            attachAuth: true,
            credentials: "same-origin",
            showError: false,
          },
        );
        if (!cancelled) {
          setText(raw);
          setError(false);
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setError(true);
          setLoading(false);
        }
      }
    };
    setLoading(true);
    void loadText();
    return () => {
      cancelled = true;
    };
  }, [path]);
  if (loading)
    return (
      <div className="w-full rounded-lg bg-muted/40 pt-[56.25%] shadow-inner" />
    );
  if (error)
    return (
      <div>
        Ошибка загрузки вложения{" "}
        <a href={buildContentByPathUrl(path)} target="_blank" rel="noreferrer">
          {id}
        </a>
      </div>
    );
  const fileLabel =
    path
      .split("/")
      .filter(Boolean)
      .pop() || id;
  return (
    <div className="rounded-md overflow-hidden border-2 border-border bg-card text-card-foreground shadow-sm">
      <div
        className="flex cursor-pointer select-none items-center justify-between gap-4 border-b border-border px-5 py-4"
        onClick={() => {
          setExpanded((prev) => {
            const next = !prev;
            const el = bodyRef.current;
            if (!el) {
              setMaxHeight(COLLAPSED_MAX);
              return next;
            }
            if (next) {
              setShowFade(false);
              const start = Math.max(el.clientHeight, COLLAPSED_MAX);
              const end = el.scrollHeight;
              setMaxHeight(start);
              void el.offsetHeight; // force reflow
              requestAnimationFrame(() => {
                setMaxHeight(end);
              });
            } else {
              setShowFade(true);
              const start = el.clientHeight;
              setMaxHeight(start);
              void el.offsetHeight; // force reflow
              requestAnimationFrame(() => {
                setMaxHeight(COLLAPSED_MAX);
              });
            }
            return next;
          });
        }}
      >
        <h4 className="m-0 text-base font-semibold">
          <a
            className="text-primary hover:underline"
            href={buildContentByPathUrl(path)}
            target="_blank"
            rel="noreferrer"
          >
            {fileLabel}
          </a>
        </h4>
        <ChevronUp
          size={18}
          className={cn(
            "shrink-0 text-muted-foreground transition-transform duration-200",
            expanded ? "rotate-180" : "rotate-0",
          )}
        />
      </div>
      <div
        ref={bodyRef}
        className={`px-6 py-4 text-sm transition-[max-height] duration-300 ease-in-out ${expanded ? "mb-6" : ""}`}
        style={{
          maxHeight: `${maxHeight}px`,
          WebkitMaskImage: showFade ? fadeMask : "none",
          maskImage: showFade ? fadeMask : "none",
        }}
      >
        <TextMarkdown>{text}</TextMarkdown>
      </div>
    </div>
  );
};

export default Text;
