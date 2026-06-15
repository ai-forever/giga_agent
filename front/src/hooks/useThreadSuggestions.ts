import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Message as Message_ } from "@langchain/langgraph-sdk";
import {
  getFollowUpSuggestions,
  getStarterSuggestions,
  PromptSuggestionsResponse,
} from "@/lib/branches-api";
import { STATIC_STARTER_RECOMMENDATIONS } from "@/config";
import {
  normalizePromptSuggestion,
  PromptSuggestionScenario,
} from "@/types/prompt-suggestions";

type StarterState = {
  suggestions: PromptSuggestionScenario[];
  sourceThreadCount: number;
  loaded: boolean;
};

const starterCache: StarterState = {
  suggestions: [],
  sourceThreadCount: 0,
  loaded: false,
};

const followUpCache = new Map<string, PromptSuggestionScenario[]>();

const normalizeSuggestions = (
  payload: PromptSuggestionsResponse | null,
): PromptSuggestionScenario[] => {
  if (!payload?.suggestions) return [];
  return payload.suggestions
    .map((item) => normalizePromptSuggestion(item))
    .filter((item): item is PromptSuggestionScenario => item !== null)
    .slice(0, 8);
};

const pickRandom = (
  pool: PromptSuggestionScenario[],
  count: number,
): PromptSuggestionScenario[] => {
  if (pool.length <= count) return [...pool];
  const copy = [...pool];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy.slice(0, count);
};

export const useStarterRecommendations = (enabled: boolean) => {
  const [suggestions, setSuggestions] = useState<PromptSuggestionScenario[]>(
    starterCache.loaded ? starterCache.suggestions : [],
  );
  const [isLoading, setIsLoading] = useState(false);
  const [sourceThreadCount, setSourceThreadCount] = useState<number>(
    starterCache.loaded ? starterCache.sourceThreadCount : 0,
  );

  const loadRecommendations = useCallback(
    async (refresh = false) => {
      if (!enabled) return;
      if (!refresh && starterCache.loaded) {
        setSuggestions(starterCache.suggestions);
        setSourceThreadCount(starterCache.sourceThreadCount);
        return;
      }
      setIsLoading(true);
      try {
        const response = await getStarterSuggestions({
          count: 3,
          limitThreads: 5,
          refresh,
        });
        const normalized = normalizeSuggestions(response).slice(0, 3);
        const next =
          normalized.length > 0
            ? normalized
            : pickRandom(STATIC_STARTER_RECOMMENDATIONS, 3);
        starterCache.suggestions = next;
        starterCache.sourceThreadCount = response.source_thread_count ?? 0;
        starterCache.loaded = true;
        setSuggestions(next);
        setSourceThreadCount(starterCache.sourceThreadCount);
      } catch {
        const fallback = pickRandom(STATIC_STARTER_RECOMMENDATIONS, 3);
        setSuggestions(fallback);
        setSourceThreadCount(0);
      } finally {
        setIsLoading(false);
      }
    },
    [enabled],
  );

  return {
    suggestions,
    isLoading,
    sourceThreadCount,
    loadRecommendations,
  };
};

const getLastAiMessageId = (messages: Message_[]): string | null => {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (msg.type === "ai" && typeof msg.id === "string" && msg.id) {
      return msg.id;
    }
  }
  return null;
};

export const useFollowUpSuggestions = ({
  threadId,
  messages,
  enabled,
}: {
  threadId?: string;
  messages: Message_[];
  enabled: boolean;
}) => {
  const [suggestions, setSuggestions] = useState<PromptSuggestionScenario[]>(
    [],
  );
  const [isLoading, setIsLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const lastAiMessageId = useMemo(
    () => getLastAiMessageId(messages),
    [messages],
  );

  useEffect(() => {
    if (!enabled || !threadId || !lastAiMessageId) {
      setSuggestions([]);
      setIsLoading(false);
      abortRef.current?.abort();
      abortRef.current = null;
      return;
    }

    const cacheKey = `${threadId}:${lastAiMessageId}`;
    const cached = followUpCache.get(cacheKey);
    if (cached) {
      setSuggestions(cached);
      setIsLoading(false);
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setIsLoading(true);

    void (async () => {
      try {
        const response = await getFollowUpSuggestions(threadId, {
          count: 3,
          pairs: 5,
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        const normalized = normalizeSuggestions(response).slice(0, 3);
        followUpCache.set(cacheKey, normalized);
        setSuggestions(normalized);
      } catch {
        if (controller.signal.aborted) return;
        setSuggestions([]);
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    })();

    return () => {
      controller.abort();
    };
  }, [enabled, threadId, lastAiMessageId]);

  return { suggestions, isLoading };
};
