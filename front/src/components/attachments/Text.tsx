import React, { useEffect, useRef, useState } from "react";
import { ChevronUp } from "lucide-react";
import axios from "axios";
import TextMarkdown from "./TextMarkdown.tsx";
import { cn } from "@/lib/utils";

interface TextProps {
  id: string;
  alt?: string;
  data: any;
}

const Text: React.FC<TextProps> = ({ id, data }) => {
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
    axios
      .get(
        `${window.location.protocol}//${window.location.host}/files${data.path}`,
      )
      .then((res) => {
        setText(res.data);
        setLoading(false);
      })
      .catch(() => {
        setError(true);
        setLoading(false);
      });
  }, [data.path]);
  if (loading)
    return (
      <div className="w-full rounded-lg bg-muted/40 pt-[56.25%] shadow-inner" />
    );
  if (error)
    return (
      <div>
        Ошибка загрузки вложения{" "}
        <a
          href={`${window.location.protocol}//${window.location.host}/files${data.path}`}
          target={"_blank"}
        >
          {id}
        </a>
      </div>
    );
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
          Файл:{" "}
          <a
            className="text-primary hover:underline"
            href={`${window.location.protocol}//${window.location.host}/files${data.path}`}
            target={"_blank"}
          >
            {id}
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
