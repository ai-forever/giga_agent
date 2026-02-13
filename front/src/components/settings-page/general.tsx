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
import type { LLMResponse } from "./forms/types";

type SecretItem = Secret & {
  id: string;
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
        typeof item === "object" && item !== null && "name" in item && "value" in item,
    )
    .map((item) => ({
      id: crypto.randomUUID(),
      name: String(item.name ?? ""),
      value: String(item.value ?? ""),
      description:
        typeof item.description === "string" ? item.description : undefined,
    }));
};

export const GeneralSettings: React.FC = () => {
  const { themeMode } = useTheme();
  const { user, refreshUser } = useAuth();

  const [llmList, setLlmList] = useState<LLMResponse[]>([]);
  const [defaultLLM, setDefaultLLM] = useState<string>("");
  const [localTheme, setLocalTheme] = useState<ThemeMode>(themeMode);
  const [instructions, setInstructions] = useState<string>("");
  const [secrets, setSecrets] = useState<SecretItem[]>([]);
  const [errors, setErrors] = useState<Record<string, Record<string, string>>>(
    {},
  );
  const [generalError, setGeneralError] = useState<string>("");
  const [isAgentSettingsOpen, setIsAgentSettingsOpen] = useState(true);
  const [loadingLLMs, setLoadingLLMs] = useState(false);
  const [saving, setSaving] = useState(false);

  // Инициализируем значения из настроек пользователя
  useEffect(() => {
    if (!user?.settings) return;
    const settings = user.settings as Record<string, unknown>;
    setDefaultLLM(
      typeof settings.default_llm === "string" ? settings.default_llm : "",
    );
    setInstructions(
      typeof settings.contextInstructions === "string"
        ? settings.contextInstructions
        : "",
    );
    setSecrets(parseSettingsSecrets(settings.contextSecrets));
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

  useEffect(() => {
    fetchLLMs();
  }, [fetchLLMs]);

  const parsedForValidation = useMemo(
    () =>
      secrets.map((s) => ({
        name: s.name ?? "",
        value: s.value ?? "",
        description: s.description ?? "",
      })),
    [secrets],
  );

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

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    try {
      const normalizedSecrets = secrets.map(({ id, ...rest }) => ({
        ...rest,
        name: rest.name.trim(),
        value: rest.value.trim(),
        description: rest.description?.trim() || undefined,
      }));
      await apiClient.patch("/api/auth/users/me/settings", {
        settings: {
          default_llm: defaultLLM || null,
          theme: localTheme,
          contextInstructions: instructions,
          contextSecrets: normalizedSecrets,
        },
      });
      // ThemeProvider подхватит тему из обновлённых user.settings
      await refreshUser();
    } catch {
      // Ошибка уже обработана глобально
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 space-y-6">
        <div className="flex items-center gap-5 grow-1 justify-between">
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
            <SelectTrigger id="theme-select" className="w-[180px]">
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
        <div className="flex items-center gap-3 grow-1 justify-between">
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
            <SelectTrigger id="default-llm-select" className="w-[180px]">
              <SelectValue
                placeholder={loadingLLMs ? "Загрузка..." : "Выберите LLM"}
              />
            </SelectTrigger>
            <SelectContent>
              {llmList.map((llm) => (
                <SelectItem key={llm.id} value={llm.id}>
                  {llm.name || llm.model_id}
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
                    <div className="text-sm text-destructive">{generalError}</div>
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
                                updateSecret(s.id, "description", e.target.value)
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
