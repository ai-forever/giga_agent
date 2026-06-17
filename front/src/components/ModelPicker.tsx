import React, { useCallback, useState } from "react";
import { Check, ChevronDown, Loader2 } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { apiClient } from "@/lib/api-client";
import { API_AGENT_PREFIX } from "@/config.ts";
import { useAuth } from "@/components/providers/auth.tsx";
import type { LLMResponse } from "@/components/settings-page/forms/types";

const llmLabel = (llm: LLMResponse): string => llm.name || llm.model_id;

const ModelPicker: React.FC<{ disabled?: boolean }> = ({ disabled }) => {
  const { user, llms, currentLlm, isLoadingLLMs, refreshUser } = useAuth();
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);

  const currentLabel = currentLlm
    ? llmLabel(currentLlm)
    : isLoadingLLMs
      ? "Загрузка…"
      : "Модель не выбрана";

  const selectLlm = useCallback(
    async (llmId: string) => {
      if (llmId === user?.llm_id || saving) return;
      setSaving(true);
      try {
        await apiClient.patch(`${API_AGENT_PREFIX}/auth/users/me`, {
          llm_id: llmId,
        });
        await refreshUser();
      } catch {
        /* handled globally */
      } finally {
        setSaving(false);
      }
    },
    [user?.llm_id, saving, refreshUser],
  );

  if (!user) return null;
  if (!isLoadingLLMs && llms.length === 0) return null;

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={disabled || saving}
          title="Выбрать модель"
          className="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors cursor-pointer outline-none disabled:opacity-60 max-w-[180px]"
        >
          {saving ? (
            <Loader2 className="size-3.5 animate-spin shrink-0" />
          ) : null}
          <span className="truncate">{currentLabel}</span>
          <ChevronDown className="size-3.5 shrink-0 opacity-70" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={6} className="min-w-[240px]">
        {llms.map((llm) => {
          const isActive = llm.id === user.llm_id;
          const label = llmLabel(llm);
          return (
            <DropdownMenuItem
              key={llm.id}
              onSelect={() => void selectLlm(llm.id)}
              className="flex items-start gap-2 py-2 cursor-pointer"
            >
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{label}</div>
                <div className="text-xs text-muted-foreground truncate">
                  {llm.model_id}
                </div>
              </div>
              {isActive && (
                <Check className="size-4 text-primary mt-0.5 shrink-0" />
              )}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default ModelPicker;
