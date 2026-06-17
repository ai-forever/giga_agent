import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiClient } from "@/lib/api-client";
import { API_AGENT_PREFIX } from "@/config";
import { useAuth } from "@/components/providers/auth";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { LLMResponse } from "@/components/settings-page/forms/types";
import type { Message } from "@langchain/langgraph-sdk";

interface ModelConfig {
  context_window: number;
  prices?: {
    cache_hit: number;
    cache_miss: number;
    output: number;
  };
}

interface ModelsConfig {
  models: Record<string, ModelConfig>;
}

interface UsageMetadata {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  input_token_details?: {
    cache_read?: number;
    cache_creation?: number;
  };
  output_token_details?: {
    reasoning?: number;
  };
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatCost(cost: number): string {
  if (cost === 0) return "$0";
  if (cost < 0.001) return `$${cost.toFixed(5)}`;
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  if (cost < 1) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
}

const SIZE = 24;
const STROKE = 2.5;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

let modelsConfigCache: ModelsConfig | null = null;
let llmsCache: LLMResponse[] | null = null;

const TokenUsageIndicator: React.FC<{ messages: Message[] }> = ({
  messages,
}) => {
  const { user } = useAuth();
  const [modelsConfig, setModelsConfig] = useState<ModelsConfig | null>(
    modelsConfigCache,
  );
  const [llms, setLlms] = useState<LLMResponse[] | null>(llmsCache);

  useEffect(() => {
    if (modelsConfigCache) return;
    apiClient
      .get<ModelsConfig>(`${API_AGENT_PREFIX}/models-config`)
      .then((data) => {
        modelsConfigCache = data;
        setModelsConfig(data);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (llmsCache) return;
    apiClient
      .get<LLMResponse[]>(`${API_AGENT_PREFIX}/llms`)
      .then((data) => {
        llmsCache = data;
        setLlms(data);
      })
      .catch(() => {});
  }, []);

  const currentModelId = useMemo(() => {
    if (!user?.llm_id || !llms) return null;
    const llm = llms.find((l) => l.id === user.llm_id);
    return llm?.model_id ?? null;
  }, [user?.llm_id, llms]);

  const modelConfig = useMemo(() => {
    if (!currentModelId || !modelsConfig) return null;
    return modelsConfig.models[currentModelId] ?? null;
  }, [currentModelId, modelsConfig]);

  const lastKnownRef = useRef<{
    contextUsed: number;
    totalCost: number;
  } | null>(null);

  const { contextUsed, totalCost } = useMemo(() => {
    const aiMessages = messages.filter((m) => m.type === "ai");
    if (aiMessages.length === 0) {
      return lastKnownRef.current ?? { contextUsed: 0, totalCost: 0 };
    }

    const lastAi = aiMessages[aiMessages.length - 1];
    const lastUsage = (lastAi as Record<string, unknown>).usage_metadata as
      | UsageMetadata
      | undefined;
    const contextUsed =
      (lastUsage?.input_tokens ?? 0) + (lastUsage?.output_tokens ?? 0);

    let totalCost = 0;
    if (modelConfig?.prices) {
      const { cache_hit, cache_miss, output } = modelConfig.prices;
      for (const msg of aiMessages) {
        const usage = (msg as Record<string, unknown>).usage_metadata as
          | UsageMetadata
          | undefined;
        if (!usage) continue;

        const outTokens = usage.output_tokens ?? 0;
        const cacheRead = usage.input_token_details?.cache_read ?? 0;
        const inputTokens = usage.input_tokens ?? 0;
        const cacheMiss = inputTokens - cacheRead;

        totalCost +=
          (cacheRead * cache_hit +
            cacheMiss * cache_miss +
            outTokens * output) /
          1_000_000;
      }
    }

    const result = { contextUsed, totalCost };
    lastKnownRef.current = result;
    return result;
  }, [messages, modelConfig]);

  if (!modelConfig || contextUsed === 0) return null;

  const contextWindow = modelConfig.context_window;
  const pct = Math.min((contextUsed / contextWindow) * 100, 100);
  const dashOffset = CIRCUMFERENCE - (pct / 100) * CIRCUMFERENCE;
  const hasPrices = modelConfig.prices != null;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          className="flex items-center justify-center cursor-default shrink-0"
          style={{ width: SIZE, height: SIZE }}
        >
          <svg
            width={SIZE}
            height={SIZE}
            viewBox={`0 0 ${SIZE} ${SIZE}`}
            className="block -rotate-90"
          >
            <circle
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke="currentColor"
              className="text-muted-foreground/20"
              strokeWidth={STROKE}
            />
            <circle
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke="currentColor"
              className="text-muted-foreground"
              strokeWidth={STROKE}
              strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={dashOffset}
              style={{ transition: "stroke-dashoffset 0.4s ease" }}
            />
          </svg>
        </div>
      </TooltipTrigger>
      <TooltipContent side="top" align="center">
        <div className="text-xs leading-relaxed">
          <div>
            {pct.toFixed(1)}% &mdash; {formatTokens(contextUsed)} /{" "}
            {formatTokens(contextWindow)} context
          </div>
          {hasPrices && totalCost > 0 && <div>{formatCost(totalCost)}</div>}
        </div>
      </TooltipContent>
    </Tooltip>
  );
};

export default TokenUsageIndicator;
