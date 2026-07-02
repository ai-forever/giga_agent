import React, { useEffect, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  ListChecks,
  SkipForward,
} from "lucide-react";
import type { AnsweredQuestion, QuestionsResult } from "../../interfaces";

const Indicator: React.FC<{ type: "single" | "multi"; checked: boolean }> = ({
  type,
  checked,
}) => (
  <span
    className={[
      "flex shrink-0 items-center justify-center",
      "w-4 h-4 border-2",
      type === "single" ? "rounded-full" : "rounded-[4px]",
      checked
        ? "border-primary bg-primary"
        : "border-muted-foreground/40 bg-transparent",
    ].join(" ")}
  >
    {checked &&
      (type === "single" ? (
        <span className="w-1.5 h-1.5 rounded-full bg-primary-foreground" />
      ) : (
        <Check className="w-3 h-3 text-primary-foreground" strokeWidth={3} />
      ))}
  </span>
);

// Label above the block, mirroring the scheduler chat card.
const Caption: React.FC<{ icon: React.ReactNode }> = ({ icon }) => (
  <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
    {icon}
    Уточняющие вопросы
  </div>
);

const QuestionPage: React.FC<{ item: AnsweredQuestion }> = ({ item }) => {
  const selectedSet = new Set(item.selected);
  const hasOther = item.other_text.trim().length > 0;
  return (
    <div className="flex flex-col gap-2">
      {item.options.map((opt, i) => {
        const checked = selectedSet.has(opt);
        return (
          <div
            key={`${opt}-${i}`}
            className={[
              "flex items-center gap-3 w-full rounded-md px-3 py-2.5 text-left",
              checked ? "bg-primary/10 ring-1 ring-primary/30" : "opacity-55",
            ].join(" ")}
          >
            <Indicator type={item.type} checked={checked} />
            <span className="text-sm text-foreground">{opt}</span>
          </div>
        );
      })}
      {hasOther && (
        <div className="flex items-center gap-3 w-full rounded-md px-3 py-2.5 bg-primary/10 ring-1 ring-primary/30">
          <Indicator type={item.type} checked />
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm text-muted-foreground shrink-0">
              Другое:
            </span>
            <span className="text-sm text-foreground truncate">
              {item.other_text}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

const AnsweredQuestionsCard: React.FC<{ data: QuestionsResult }> = ({
  data,
}) => {
  const [currentPage, setCurrentPage] = useState(0);
  const [hovered, setHovered] = useState(false);

  const total = data.skipped ? 0 : data.items.length;

  // Arrow-key paging while the card is hovered. Scoped to hover so multiple
  // cards in a thread don't all react to the same keypress.
  useEffect(() => {
    if (!hovered || total <= 1) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setCurrentPage((p) => Math.max(0, p - 1));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        setCurrentPage((p) => Math.min(total - 1, p + 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [hovered, total]);

  if (data.skipped) {
    return (
      <div className="space-y-1.5">
        <Caption icon={<SkipForward className="size-3.5" />} />
        <div className="rounded-lg border border-border/60 bg-muted/10 px-4 py-3 text-sm text-muted-foreground">
          {data.comment
            ? `Пользователь пропустил вопросы и ответил: «${data.comment}»`
            : "Пользователь пропустил вопросы."}
        </div>
      </div>
    );
  }

  if (total === 0) return null;
  const page = Math.min(currentPage, total - 1);
  const item = data.items[page];

  return (
    <div
      className="space-y-1.5"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <Caption icon={<ListChecks className="size-3.5" />} />
      <div className="rounded-lg border border-border/60 bg-muted/10 overflow-hidden">
        <div className="p-4 pb-3">
          {/* Header: question text + page number */}
          <div className="flex items-start justify-between gap-3 mb-3">
            <p className="text-sm font-medium text-foreground leading-snug">
              {item.question}
            </p>
            {total > 1 && (
              <span className="text-xs text-muted-foreground whitespace-nowrap tabular-nums pt-0.5">
                {page + 1}/{total}
              </span>
            )}
          </div>

          <QuestionPage item={item} />
        </div>

        {/* Footer: gallery navigation */}
        {total > 1 && (
          <div className="flex items-center justify-center gap-1.5 px-4 py-2.5 border-t border-border/30 bg-muted/5">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setCurrentPage(page - 1)}
              className="w-7 h-7 rounded-full flex items-center justify-center text-muted-foreground hover:bg-muted/40 transition-colors disabled:opacity-30 disabled:cursor-default cursor-pointer"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="text-xs text-muted-foreground tabular-nums min-w-[3ch] text-center">
              {page + 1} / {total}
            </span>
            <button
              type="button"
              disabled={page === total - 1}
              onClick={() => setCurrentPage(page + 1)}
              className="w-7 h-7 rounded-full flex items-center justify-center text-muted-foreground hover:bg-muted/40 transition-colors disabled:opacity-30 disabled:cursor-default cursor-pointer"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default AnsweredQuestionsCard;
