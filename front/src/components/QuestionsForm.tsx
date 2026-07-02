import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Send,
  SkipForward,
} from "lucide-react";
import type { Question, QuestionAnswer } from "../interfaces";

interface AnswerState {
  selected: Set<string>;
  otherSelected: boolean;
  otherText: string;
}

type AnswerMap = Record<string, AnswerState>;

const hasAnswer = (a: AnswerState): boolean =>
  a.selected.size > 0 || (a.otherSelected && a.otherText.trim().length > 0);

interface QuestionsFormProps {
  questions: Question[];
  onSubmit: (answers: QuestionAnswer[]) => void;
  onSkip: () => void;
  disabled?: boolean;
}

const QuestionsForm: React.FC<QuestionsFormProps> = ({
  questions,
  onSubmit,
  onSkip,
  disabled = false,
}) => {
  const [currentPage, setCurrentPage] = useState(0);
  const [answers, setAnswers] = useState<AnswerMap>(() => {
    const initial: AnswerMap = {};
    for (const q of questions) {
      initial[q.id] = {
        selected: new Set(),
        otherSelected: false,
        otherText: "",
      };
    }
    return initial;
  });
  const [submitted, setSubmitted] = useState(false);
  const otherInputRef = useRef<HTMLInputElement>(null);

  // Arrow-key paging for the gallery. Ignored while typing in the "Other"
  // field so arrows move the caret there instead of flipping pages.
  useEffect(() => {
    const total = questions.length;
    if (total <= 1 || disabled || submitted) return;
    const onKey = (e: KeyboardEvent) => {
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
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
  }, [questions.length, disabled, submitted]);

  const question = questions[currentPage];
  if (!question) return null;

  const answer = answers[question.id];
  const totalPages = questions.length;
  const isDisabled = disabled || submitted;

  const handleOptionClick = useCallback(
    (optionId: string) => {
      if (isDisabled) return;
      setAnswers((prev) => {
        const current = prev[question.id];
        if (question.type === "single") {
          return {
            ...prev,
            [question.id]: {
              selected: new Set([optionId]),
              otherSelected: false,
              otherText: "",
            },
          };
        }
        const newSet = new Set(current.selected);
        if (newSet.has(optionId)) newSet.delete(optionId);
        else newSet.add(optionId);
        return {
          ...prev,
          [question.id]: { ...current, selected: newSet },
        };
      });
      if (question.type === "single" && currentPage < totalPages - 1) {
        setTimeout(() => setCurrentPage((p) => p + 1), 180);
      }
    },
    [isDisabled, question.id, question.type, currentPage, totalPages],
  );

  const selectOther = useCallback(() => {
    if (isDisabled) return;
    setAnswers((prev) => {
      const current = prev[question.id];
      if (question.type === "single") {
        setTimeout(() => otherInputRef.current?.focus(), 0);
        return {
          ...prev,
          [question.id]: {
            selected: new Set<string>(),
            otherSelected: true,
            otherText: current.otherText,
          },
        };
      }
      const willSelect = !current.otherSelected;
      if (willSelect) {
        setTimeout(() => otherInputRef.current?.focus(), 0);
      }
      return {
        ...prev,
        [question.id]: {
          ...current,
          otherSelected: willSelect,
          otherText: willSelect ? current.otherText : "",
        },
      };
    });
  }, [isDisabled, question.id, question.type]);

  const handleOtherTextChange = useCallback(
    (text: string) => {
      setAnswers((prev) => {
        const current = prev[question.id];
        const patch: Partial<AnswerState> = { otherText: text };
        if (!current.otherSelected && text) {
          patch.otherSelected = true;
          if (question.type === "single") patch.selected = new Set<string>();
        }
        return {
          ...prev,
          [question.id]: { ...current, ...patch },
        };
      });
    },
    [question.id, question.type],
  );

  const allAnswered = questions.every((q) => hasAnswer(answers[q.id]));

  const handleSubmit = useCallback(() => {
    if (isDisabled || !allAnswered) return;
    setSubmitted(true);
    const result: QuestionAnswer[] = questions.map((q) => {
      const a = answers[q.id];
      return {
        question_id: q.id,
        selected: Array.from(a.selected),
        other_text: a.otherSelected ? a.otherText : "",
      };
    });
    onSubmit(result);
  }, [isDisabled, allAnswered, questions, answers, onSubmit]);

  const handleSkip = useCallback(() => {
    if (isDisabled) return;
    setSubmitted(true);
    onSkip();
  }, [isDisabled, onSkip]);

  const Indicator: React.FC<{
    type: "single" | "multi";
    checked: boolean;
  }> = ({ type, checked }) => (
    <span
      className={[
        "flex shrink-0 items-center justify-center transition-colors",
        type === "single"
          ? "w-4 h-4 rounded-full border-2"
          : "w-4 h-4 rounded-[4px] border-2",
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

  return (
    <div className="mt-2 mb-2 rounded-lg border border-border/60 bg-muted/10 overflow-hidden">
      <div className="p-4 pb-3">
        {/* Header: question text + page number */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <p className="text-sm font-medium text-foreground leading-snug">
            {question.text}
          </p>
          {totalPages > 1 && (
            <span className="text-xs text-muted-foreground whitespace-nowrap tabular-nums pt-0.5">
              {currentPage + 1}/{totalPages}
            </span>
          )}
        </div>

        {/* Options */}
        <div className="flex flex-col gap-0.5">
          {question.options.map((opt) => {
            const isSelected = answer.selected.has(opt.id);
            return (
              <button
                key={opt.id}
                type="button"
                disabled={isDisabled}
                onClick={() => handleOptionClick(opt.id)}
                className={[
                  "flex items-center gap-3 w-full rounded-md px-3 py-2.5 text-left transition-colors",
                  isSelected
                    ? "bg-primary/10 ring-1 ring-primary/30"
                    : "hover:bg-muted/40",
                  isDisabled ? "opacity-60 cursor-default" : "cursor-pointer",
                ].join(" ")}
              >
                <Indicator type={question.type} checked={isSelected} />
                <span className="text-sm text-foreground">{opt.text}</span>
              </button>
            );
          })}

          {/* "Other" option */}
          <div
            role="button"
            tabIndex={isDisabled ? undefined : 0}
            onClick={() => !isDisabled && selectOther()}
            onKeyDown={(e) => {
              if (!isDisabled && (e.key === "Enter" || e.key === " ")) {
                e.preventDefault();
                selectOther();
              }
            }}
            className={[
              "flex items-center gap-3 w-full rounded-md px-3 py-2.5 text-left transition-colors",
              answer.otherSelected
                ? "bg-primary/10 ring-1 ring-primary/30"
                : "hover:bg-muted/40",
              isDisabled ? "opacity-60 cursor-default" : "cursor-pointer",
            ].join(" ")}
          >
            <Indicator type={question.type} checked={answer.otherSelected} />
            <div className="flex-1 flex items-center gap-2 min-w-0">
              <span className="text-sm text-muted-foreground shrink-0">
                Другое:
              </span>
              <input
                ref={otherInputRef}
                type="text"
                value={answer.otherText}
                onChange={(e) => handleOtherTextChange(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                onFocus={() => {
                  if (!answer.otherSelected) selectOther();
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                  }
                  e.stopPropagation();
                }}
                disabled={isDisabled}
                placeholder="Введите свой вариант…"
                className="flex-1 min-w-0 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/50 border-b border-muted-foreground/20 focus:border-primary py-0.5 transition-colors"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Footer: navigation + submit */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-border/30 bg-muted/5">
        {/* Pagination */}
        <div className="flex items-center gap-1.5">
          {totalPages > 1 && (
            <>
              <button
                type="button"
                disabled={currentPage === 0 || isDisabled}
                onClick={() => setCurrentPage((p) => p - 1)}
                className="w-7 h-7 rounded-full flex items-center justify-center text-muted-foreground hover:bg-muted/40 transition-colors disabled:opacity-30 disabled:cursor-default cursor-pointer"
              >
                <ChevronLeft size={16} />
              </button>
              <span className="text-xs text-muted-foreground tabular-nums min-w-[3ch] text-center">
                {currentPage + 1} / {totalPages}
              </span>
              <button
                type="button"
                disabled={currentPage === totalPages - 1 || isDisabled}
                onClick={() => setCurrentPage((p) => p + 1)}
                className="w-7 h-7 rounded-full flex items-center justify-center text-muted-foreground hover:bg-muted/40 transition-colors disabled:opacity-30 disabled:cursor-default cursor-pointer"
              >
                <ChevronRight size={16} />
              </button>
            </>
          )}
        </div>

        {/* Skip + Submit */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={isDisabled}
            onClick={handleSkip}
            className="inline-flex items-center gap-2 rounded-md border border-border/60 px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground disabled:opacity-50 disabled:cursor-default cursor-pointer"
          >
            <SkipForward size={14} />
            Пропустить
          </button>
          <button
            type="button"
            disabled={isDisabled || !allAnswered}
            onClick={handleSubmit}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50 disabled:cursor-default cursor-pointer"
          >
            <Send size={14} />
            Отправить
          </button>
        </div>
      </div>
    </div>
  );
};

export default QuestionsForm;
