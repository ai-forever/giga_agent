import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  Sun,
  Moon,
  Monitor,
  Loader2,
  Plus,
  Trash2,
  ChevronDown,
} from "lucide-react";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Input, SecretInput } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTheme, ThemeMode } from "@/components/providers/theme.tsx";
import { useAuth } from "@/components/providers/auth.tsx";
import { apiClient } from "@/lib/api-client";
import { z } from "zod";
import { AnimatePresence, motion } from "framer-motion";
import type { Secret } from "@/interfaces.ts";
import type {
  EmbeddingResponse,
  ImageGeneratorResponse,
  LLMResponse,
  SearchEngineResponse,
} from "./forms/types";

const NO_EMBEDDING_VALUE = "__none__";
const NO_IMAGE_GENERATOR_VALUE = "__none__";
const NO_SEARCH_ENGINE_VALUE = "__none__";
const NO_LLM_VALUE = "__none_llm__";
const FAST_LLM_INHERIT_VALUE = "__inherit__";

type SecretItem = Secret & {
  id: string;
};

type AgentSecretMeta = {
  name: string;
  description?: string | null;
};

const secretSchema = z.object({
  name: z.string().trim().min(1, "Заполните название"),
  value: z.string().trim().min(1, "Заполните значение"),
  description: z.string().optional(),
});

const secretsArraySchema = z.array(secretSchema).superRefine((items, ctx) => {
  const seen = new Map<string, number[]>();
  items.forEach((item, index) => {
    const key = item.name.trim().toLowerCase();
    if (!seen.has(key)) seen.set(key, []);
    seen.get(key)!.push(index);
  });
  for (const [, indices] of seen) {
    if (indices.length > 1) {
      indices.forEach((i) => {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Названия секретов должны быть уникальными",
          path: [i, "name"],
        });
      });
    }
  }
});

const parseSettingsSecrets = (value: unknown): SecretItem[] => {
  if (!Array.isArray(value)) return [];
  return value
    .filter(
      (item): item is Secret =>
        typeof item === "object" &&
        item !== null &&
        "name" in item &&
        "value" in item,
    )
    .map((item) => ({
      id: crypto.randomUUID(),
      name: String(item.name ?? ""),
      value: String(item.value ?? ""),
      description:
        typeof item.description === "string" ? item.description : undefined,
    }));
};

const normalizeSecrets = (items: SecretItem[]) =>
  items.map(({ id, ...rest }) => ({
    ...rest,
    name: rest.name.trim(),
    value: rest.value.trim(),
    description: rest.description?.trim() || undefined,
  }));

const parseUserSecrets = (value: unknown): Record<string, string> => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }

  const parsed: Record<string, string> = {};
  for (const [key, rawValue] of Object.entries(value)) {
    if (typeof rawValue === "string") {
      parsed[key] = rawValue;
      continue;
    }
    if (rawValue == null) {
      parsed[key] = "";
      continue;
    }
    parsed[key] = String(rawValue);
  }
  return parsed;
};

const dedupeAgentSecretsMeta = (items: AgentSecretMeta[]): AgentSecretMeta[] => {
  const seen = new Set<string>();
  const deduped: AgentSecretMeta[] = [];
  for (const item of items) {
    if (!item?.name || seen.has(item.name)) continue;
    seen.add(item.name);
    deduped.push(item);
  }
  return deduped;
};

export const GeneralSettings: React.FC = () => {
  const { themeMode } = useTheme();
  const { user, refreshUser } = useAuth();

  const [llmList, setLlmList] = useState<LLMResponse[]>([]);
  const [embeddingList, setEmbeddingList] = useState<EmbeddingResponse[]>([]);
  const [imageGeneratorList, setImageGeneratorList] = useState<
    ImageGeneratorResponse[]
  >([]);
  const [searchEngineList, setSearchEngineList] = useState<
    SearchEngineResponse[]
  >([]);
  const [agentSecretMeta, setAgentSecretMeta] = useState<AgentSecretMeta[]>([]);
  const [loadingAgentSecrets, setLoadingAgentSecrets] = useState(false);
  const [agentSecretsValues, setAgentSecretsValues] = useState<
    Record<string, string>
  >({});
  const [defaultLLM, setDefaultLLM] = useState<string>(NO_LLM_VALUE);
  const [fastLLM, setFastLLM] = useState<string>(FAST_LLM_INHERIT_VALUE);
  const [currentEmbedding, setCurrentEmbedding] =
    useState<string>(NO_EMBEDDING_VALUE);
  const [currentImageGenerator, setCurrentImageGenerator] = useState<string>(
    NO_IMAGE_GENERATOR_VALUE,
  );
  const [currentSearchEngine, setCurrentSearchEngine] = useState<string>(
    NO_SEARCH_ENGINE_VALUE,
  );
  const [localTheme, setLocalTheme] = useState<ThemeMode>(themeMode);
  const [instructions, setInstructions] = useState<string>("");
  const [secrets, setSecrets] = useState<SecretItem[]>([]);
  const [errors, setErrors] = useState<Record<string, Record<string, string>>>(
    {},
  );
  const [generalError, setGeneralError] = useState<string>("");
  const [isAgentSettingsOpen, setIsAgentSettingsOpen] = useState(true);
  const [loadingLLMs, setLoadingLLMs] = useState(false);
  const [loadingEmbeddings, setLoadingEmbeddings] = useState(false);
  const [loadingImageGenerators, setLoadingImageGenerators] = useState(false);
  const [loadingSearchEngines, setLoadingSearchEngines] = useState(false);
  const [saving, setSaving] = useState(false);

  // Инициализируем значения из профиля пользователя
  useEffect(() => {
    if (!user) return;
    const settings = (user.settings ?? {}) as Record<string, unknown>;
    setDefaultLLM(user.llm_id ?? NO_LLM_VALUE);
    setFastLLM(user.fast_llm_id ?? FAST_LLM_INHERIT_VALUE);
    setCurrentEmbedding(user.embedding_id ?? NO_EMBEDDING_VALUE);
    setCurrentImageGenerator(
      user.image_generator_id ?? NO_IMAGE_GENERATOR_VALUE,
    );
    setCurrentSearchEngine(user.search_engine_id ?? NO_SEARCH_ENGINE_VALUE);
    setInstructions(
      typeof settings.contextInstructions === "string"
        ? settings.contextInstructions
        : "",
    );
    setSecrets(parseSettingsSecrets(settings.contextSecrets));
    setAgentSecretsValues(parseUserSecrets(user.secrets));
  }, [user]);

  // Синхронизируем локальную тему с themeMode из провайдера
  // (ThemeProvider сам подхватывает тему из user.settings)
  useEffect(() => {
    setLocalTheme(themeMode);
  }, [themeMode]);

  const fetchLLMs = useCallback(async () => {
    setLoadingLLMs(true);
    try {
      const data = await apiClient.get<LLMResponse[]>("/api/llms");
      setLlmList(data);
    } catch {
      // Ошибка уже обработана глобально
    } finally {
      setLoadingLLMs(false);
    }
  }, []);

  const fetchEmbeddings = useCallback(async () => {
    setLoadingEmbeddings(true);
    try {
      const embeddings = await apiClient.get<EmbeddingResponse[]>(
        "/api/embeddings?only_active=true",
      );
      setEmbeddingList(embeddings);
    } catch {
      // Ошибка уже обработана глобально
    } finally {
      setLoadingEmbeddings(false);
    }
  }, []);

  const fetchImageGenerators = useCallback(async () => {
    setLoadingImageGenerators(true);
    try {
      const generators = await apiClient.get<ImageGeneratorResponse[]>(
        "/api/generators/image?only_active=true",
      );
      setImageGeneratorList(generators);
    } catch {
      // Ошибка уже обработана глобально
    } finally {
      setLoadingImageGenerators(false);
    }
  }, []);

  const fetchSearchEngines = useCallback(async () => {
    setLoadingSearchEngines(true);
    try {
      const engines = await apiClient.get<SearchEngineResponse[]>(
        "/api/search-engines?only_active=true",
      );
      setSearchEngineList(engines);
    } catch {
      // Ошибка уже обработана глобально
    } finally {
      setLoadingSearchEngines(false);
    }
  }, []);

  const fetchAgentSecrets = useCallback(async () => {
    setLoadingAgentSecrets(true);
    try {
      const secretsMeta =
        await apiClient.get<AgentSecretMeta[]>("/api/agent/secrets");
      setAgentSecretMeta(dedupeAgentSecretsMeta(secretsMeta));
    } catch {
      setAgentSecretMeta([]);
      // Ошибка уже обработана глобально
    } finally {
      setLoadingAgentSecrets(false);
    }
  }, []);

  useEffect(() => {
    fetchLLMs();
    fetchEmbeddings();
    fetchImageGenerators();
    fetchSearchEngines();
    fetchAgentSecrets();
  }, [
    fetchLLMs,
    fetchEmbeddings,
    fetchImageGenerators,
    fetchSearchEngines,
    fetchAgentSecrets,
  ]);

  const parsedForValidation = useMemo(
    () =>
      secrets.map((s) => ({
        name: s.name ?? "",
        value: s.value ?? "",
        description: s.description ?? "",
      })),
    [secrets],
  );
  const selectedDefaultLlmLabel = useMemo(() => {
    if (defaultLLM === NO_LLM_VALUE) return "Не выбрана";
    const selected = llmList.find((llm) => llm.id === defaultLLM);
    return selected ? selected.name || selected.model_id : "Не выбрана";
  }, [llmList, defaultLLM]);

  const validate = (): boolean => {
    setGeneralError("");
    setErrors({});
    const result = secretsArraySchema.safeParse(parsedForValidation);
    if (result.success) return true;

    const fieldErrors: Record<string, Record<string, string>> = {};
    for (const issue of result.error.issues) {
      if (
        Array.isArray(issue.path) &&
        issue.path.length === 2 &&
        typeof issue.path[0] === "number" &&
        typeof issue.path[1] === "string"
      ) {
        const index = issue.path[0] as number;
        const field = issue.path[1] as string;
        const id = secrets[index]?.id;
        if (!id) continue;
        if (!fieldErrors[id]) fieldErrors[id] = {};
        fieldErrors[id][field] = issue.message;
      } else {
        setGeneralError(issue.message);
      }
    }
    setErrors(fieldErrors);
    return false;
  };

  const addSecret = () => {
    setSecrets((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        name: "",
        value: "",
        description: "",
      },
    ]);
  };

  const removeSecret = (id: string) => {
    setSecrets((prev) => prev.filter((s) => s.id !== id));
    setErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };

  const updateSecret = <K extends keyof SecretItem>(
    id: string,
    key: K,
    value: SecretItem[K],
  ) => {
    setSecrets((prev) =>
      prev.map((s) => (s.id === id ? { ...s, [key]: value } : s)),
    );
  };

  const updateAgentSecretValue = (name: string, value: string) => {
    setAgentSecretsValues((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    try {
      const patchBody: Record<string, unknown> = {};
      const currentSettings = (user?.settings ?? {}) as Record<string, unknown>;
      const settingsPatch: Record<string, unknown> = {};

      const currentTheme =
        typeof currentSettings.theme === "string"
          ? (currentSettings.theme as ThemeMode)
          : "system";
      if (localTheme !== currentTheme) {
        settingsPatch.theme = localTheme;
      }

      const currentInstructions =
        typeof currentSettings.contextInstructions === "string"
          ? currentSettings.contextInstructions
          : "";
      if (instructions !== currentInstructions) {
        settingsPatch.contextInstructions = instructions;
      }

      const normalizedSecrets = normalizeSecrets(secrets);
      const currentSecrets = normalizeSecrets(
        parseSettingsSecrets(currentSettings.contextSecrets),
      );
      if (
        JSON.stringify(normalizedSecrets) !== JSON.stringify(currentSecrets)
      ) {
        settingsPatch.contextSecrets = normalizedSecrets;
      }

      if (Object.keys(settingsPatch).length > 0) {
        patchBody.settings = settingsPatch;
      }

      const currentUserSecrets =
        typeof user?.secrets === "object" &&
        user.secrets !== null &&
        !Array.isArray(user.secrets)
          ? (user.secrets as Record<string, unknown>)
          : {};
      const normalizedAgentSecretsValues: Record<string, string> = {};
      for (const secretMeta of agentSecretMeta) {
        normalizedAgentSecretsValues[secretMeta.name] = (
          agentSecretsValues[secretMeta.name] ?? ""
        ).trim();
      }

      const hasAgentSecretChanges = agentSecretMeta.some((secretMeta) => {
        const currentRaw = currentUserSecrets[secretMeta.name];
        const currentValue =
          typeof currentRaw === "string"
            ? currentRaw.trim()
            : currentRaw == null
              ? ""
              : String(currentRaw).trim();
        return normalizedAgentSecretsValues[secretMeta.name] !== currentValue;
      });

      if (hasAgentSecretChanges) {
        patchBody.secrets = {
          ...currentUserSecrets,
          ...normalizedAgentSecretsValues,
        };
      }

      if (defaultLLM !== (user?.llm_id ?? NO_LLM_VALUE)) {
        patchBody.llm_id = defaultLLM === NO_LLM_VALUE ? null : defaultLLM;
      }

      const initialFastValue = user?.fast_llm_id ?? FAST_LLM_INHERIT_VALUE;
      if (fastLLM !== initialFastValue) {
        patchBody.fast_llm_id =
          fastLLM === FAST_LLM_INHERIT_VALUE ? null : fastLLM;
      }

      if (currentEmbedding !== (user?.embedding_id ?? NO_EMBEDDING_VALUE)) {
        patchBody.embedding_id =
          currentEmbedding === NO_EMBEDDING_VALUE ? null : currentEmbedding;
      }

      if (
        currentImageGenerator !==
        (user?.image_generator_id ?? NO_IMAGE_GENERATOR_VALUE)
      ) {
        patchBody.image_generator_id =
          currentImageGenerator === NO_IMAGE_GENERATOR_VALUE
            ? null
            : currentImageGenerator;
      }

      if (
        currentSearchEngine !==
        (user?.search_engine_id ?? NO_SEARCH_ENGINE_VALUE)
      ) {
        patchBody.search_engine_id =
          currentSearchEngine === NO_SEARCH_ENGINE_VALUE
            ? null
            : currentSearchEngine;
      }

      if (Object.keys(patchBody).length > 0) {
        await apiClient.patch("/api/auth/users/me", patchBody);
      }

      await refreshUser();
    } catch {
      // Ошибка уже обработана глобально
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 space-y-6 pb-20">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_260px] md:items-center">
          <Label className="block" htmlFor="theme-select">
            <div>Тема оформления</div>
            <p className="text-sm text-muted-foreground mt-2">
              Настройте тему интерфейса
            </p>
          </Label>
          <Select
            value={localTheme}
            onValueChange={(value) => setLocalTheme(value as ThemeMode)}
          >
            <SelectTrigger id="theme-select" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="system">
                <Monitor className="size-4 mr-1.5 inline-block" />
                Системная
              </SelectItem>
              <SelectItem value="light">
                <Sun className="size-4 mr-1.5 inline-block" />
                Светлая
              </SelectItem>
              <SelectItem value="dark">
                <Moon className="size-4 mr-1.5 inline-block" />
                Тёмная
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_260px] md:items-center">
          <Label className="block grow-1" htmlFor="default-llm-select">
            <div>Модель по умолчанию</div>
            <p className="text-sm text-muted-foreground mt-2">
              Выберите LLM, которая будет использоваться по умолчанию
            </p>
          </Label>
          <Select
            value={defaultLLM}
            onValueChange={setDefaultLLM}
            disabled={loadingLLMs}
          >
            <SelectTrigger id="default-llm-select" className="w-full">
              <SelectValue
                placeholder={loadingLLMs ? "Загрузка..." : "Выберите LLM"}
              />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_LLM_VALUE}>Не выбрана</SelectItem>
              {llmList.map((llm) => (
                <SelectItem key={llm.id} value={llm.id}>
                  {llm.name || llm.model_id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_260px] md:items-center">
          <Label className="block grow-1" htmlFor="fast-llm-select">
            <div>Быстрая модель</div>
            <p className="text-sm text-muted-foreground mt-2">
              Используется в быстрых и вспомогательных задачах. Если не выбрана,
              наследуется основная модель.
            </p>
          </Label>
          <Select
            value={fastLLM}
            onValueChange={setFastLLM}
            disabled={loadingLLMs}
          >
            <SelectTrigger id="fast-llm-select" className="w-full">
              <SelectValue
                placeholder={loadingLLMs ? "Загрузка..." : "Выберите LLM"}
              />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={FAST_LLM_INHERIT_VALUE}>
                ({selectedDefaultLlmLabel})
              </SelectItem>
              {llmList.map((llm) => (
                <SelectItem key={llm.id} value={llm.id}>
                  {llm.name || llm.model_id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_260px] md:items-center">
          <Label className="block grow-1" htmlFor="default-embedding-select">
            <div>Embeddings</div>
            <p className="text-sm text-muted-foreground mt-2">
              Выберите embedding модель по умолчанию
            </p>
          </Label>
          <Select
            value={currentEmbedding}
            onValueChange={setCurrentEmbedding}
            disabled={loadingEmbeddings}
          >
            <SelectTrigger id="default-embedding-select" className="w-full">
              <SelectValue
                placeholder={loadingEmbeddings ? "Загрузка..." : "Не выбран"}
              />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_EMBEDDING_VALUE}>Не выбран</SelectItem>
              {embeddingList.map((embedding) => (
                <SelectItem key={embedding.id} value={embedding.id}>
                  {embedding.name || embedding.model_id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_260px] md:items-center">
          <Label
            className="block grow-1"
            htmlFor="default-image-generator-select"
          >
            <div>Image generator</div>
            <p className="text-sm text-muted-foreground mt-2">
              Выберите генератор изображений по умолчанию
            </p>
          </Label>
          <Select
            value={currentImageGenerator}
            onValueChange={setCurrentImageGenerator}
            disabled={loadingImageGenerators}
          >
            <SelectTrigger
              id="default-image-generator-select"
              className="w-full"
            >
              <SelectValue
                placeholder={
                  loadingImageGenerators ? "Загрузка..." : "Не выбран"
                }
              />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_IMAGE_GENERATOR_VALUE}>
                Не выбран
              </SelectItem>
              {imageGeneratorList.map((generator) => (
                <SelectItem key={generator.id} value={generator.id}>
                  {generator.name || generator.type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_260px] md:items-center">
          <Label
            className="block grow-1"
            htmlFor="default-search-engine-select"
          >
            <div>Search engine</div>
            <p className="text-sm text-muted-foreground mt-2">
              Выберите поисковый движок по умолчанию
            </p>
          </Label>
          <Select
            value={currentSearchEngine}
            onValueChange={setCurrentSearchEngine}
            disabled={loadingSearchEngines}
          >
            <SelectTrigger id="default-search-engine-select" className="w-full">
              <SelectValue
                placeholder={loadingSearchEngines ? "Загрузка..." : "Не выбран"}
              />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_SEARCH_ENGINE_VALUE}>Не выбран</SelectItem>
              {searchEngineList.map((engine) => (
                <SelectItem key={engine.id} value={engine.id}>
                  {engine.name || engine.type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-2 pt-2">
          <button
            type="button"
            onClick={() => setIsAgentSettingsOpen((prev) => !prev)}
            className="flex items-center gap-2 cursor-pointer"
          >
            <span className="text-base font-semibold whitespace-nowrap">
              Настройки агента
            </span>
            <ChevronDown
              size={18}
              className={`transition-transform duration-200 ${
                isAgentSettingsOpen ? "rotate-0" : "-rotate-90"
              }`}
            />
          </button>
          <hr className="w-full border-border ml-1" />
        </div>

        <AnimatePresence initial={false}>
          {isAgentSettingsOpen && (
            <motion.div
              key="agent-settings"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2, ease: "easeInOut" }}
              className="overflow-hidden"
            >
              <div className="space-y-6 pt-1">
                <section className="space-y-2">
                  <h3 className="font-medium text-sm">Доп. инструкции</h3>
                  <p className="text-sm text-muted-foreground">
                    Укажите дополнительные инструкции по поведению агента
                  </p>
                  <Textarea
                    placeholder="Опишите предпочитаемый стиль, ограничения, тон и т.п."
                    value={instructions}
                    onChange={(e) => setInstructions(e.target.value)}
                    className="min-h-28 max-h-67"
                  />
                </section>

                <section className="space-y-3">
                  <div>
                    <h3 className="font-medium text-sm">API-ключи модулей</h3>
                    <p className="text-sm text-muted-foreground">
                      Ключи, которые запрашиваются активными модулями агента.
                    </p>
                  </div>

                  {loadingAgentSecrets && (
                    <div className="text-sm text-muted-foreground">
                      Загрузка API-ключей...
                    </div>
                  )}

                  {!loadingAgentSecrets && agentSecretMeta.length === 0 && (
                    <div className="text-sm text-muted-foreground">
                      Модули не запросили API-ключи.
                    </div>
                  )}

                  <div className="space-y-3">
                    {agentSecretMeta.map((secretMeta) => (
                      <div
                        key={secretMeta.name}
                        className="border rounded-lg p-3 bg-muted/40"
                      >
                        <div className="grid gap-3 md:grid-cols-2 md:items-center">
                          <div className="space-y-1.5">
                            <Label htmlFor={`agent-secret-${secretMeta.name}`}>
                              {secretMeta.name}
                            </Label>
                            {secretMeta.description && (
                              <p className="text-sm text-muted-foreground">
                                {secretMeta.description}
                              </p>
                            )}
                          </div>
                          <SecretInput
                            id={`agent-secret-${secretMeta.name}`}
                            placeholder="Введите значение API-ключа"
                            value={agentSecretsValues[secretMeta.name] ?? ""}
                            onChange={(e) =>
                              updateAgentSecretValue(
                                secretMeta.name,
                                e.target.value,
                              )
                            }
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="font-medium text-sm">Секреты</h3>
                      <p className="text-sm text-muted-foreground">
                        Здесь хранятся секретные значения: Credentials,
                        AuthTokens и т.д.
                      </p>
                    </div>
                    <Button type="button" variant="outline" onClick={addSecret}>
                      <Plus size={16} />
                      Добавить секрет
                    </Button>
                  </div>

                  {generalError && (
                    <div className="text-sm text-destructive">
                      {generalError}
                    </div>
                  )}

                  <div className="space-y-4">
                    {secrets.length === 0 && (
                      <div className="text-sm text-muted-foreground">
                        Секреты пока не добавлены.
                      </div>
                    )}

                    {secrets.map((s) => {
                      const err = errors[s.id] || {};
                      return (
                        <div
                          key={s.id}
                          className="border rounded-lg p-3 bg-muted/40"
                        >
                          <div className="flex items-start gap-2">
                            <div className="flex-1 grid grid-cols-2 gap-2">
                              <div>
                                <Input
                                  placeholder="Название"
                                  value={s.name}
                                  onChange={(e) =>
                                    updateSecret(s.id, "name", e.target.value)
                                  }
                                  aria-invalid={Boolean(err.name)}
                                />
                                {err.name && (
                                  <div className="mt-1 text-xs text-destructive">
                                    {err.name}
                                  </div>
                                )}
                              </div>
                              <div>
                                <SecretInput
                                  placeholder="Значение"
                                  value={s.value}
                                  onChange={(e) =>
                                    updateSecret(s.id, "value", e.target.value)
                                  }
                                  aria-invalid={Boolean(err.value)}
                                />
                                {err.value && (
                                  <div className="mt-1 text-xs text-destructive">
                                    {err.value}
                                  </div>
                                )}
                              </div>
                            </div>
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label="Удалить секрет"
                              onClick={() => removeSecret(s.id)}
                              title="Удалить секрет"
                            >
                              <Trash2 size={16} />
                            </Button>
                          </div>

                          <div className="mt-2">
                            <Input
                              placeholder="Описание (где/как применять секрет)"
                              value={s.description ?? ""}
                              onChange={(e) =>
                                updateSecret(
                                  s.id,
                                  "description",
                                  e.target.value,
                                )
                              }
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Закреплённая кнопка сохранения */}
      <div className="sticky bottom-0 pt-6 pb-2 bg-gradient-to-t from-card from-60% to-transparent">
        <Button
          onClick={handleSave}
          variant="default2"
          disabled={saving}
          className="float-right"
        >
          {saving && <Loader2 className="size-4 mr-2 animate-spin" />}
          Сохранить
        </Button>
      </div>
    </div>
  );
};

export default GeneralSettings;
