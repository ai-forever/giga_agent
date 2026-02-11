import React, { useState, useEffect, useCallback } from "react";
import { Sun, Moon, Monitor, Loader2 } from "lucide-react";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
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
import type { LLMResponse } from "./forms/types";

export const GeneralSettings: React.FC = () => {
  const { themeMode } = useTheme();
  const { user, refreshUser } = useAuth();

  const [llmList, setLlmList] = useState<LLMResponse[]>([]);
  const [defaultLLM, setDefaultLLM] = useState<string>("");
  const [localTheme, setLocalTheme] = useState<ThemeMode>(themeMode);
  const [loadingLLMs, setLoadingLLMs] = useState(false);
  const [saving, setSaving] = useState(false);

  // Инициализируем значения из настроек пользователя
  useEffect(() => {
    if (user?.settings) {
      const settings = user.settings as Record<string, unknown>;
      if (settings.default_llm) {
        setDefaultLLM(settings.default_llm as string);
      }
    }
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

  const handleSave = async () => {
    setSaving(true);
    try {
      console.log("localTheme", localTheme);
      await apiClient.patch("/api/auth/users/me/settings", {
        settings: {
          default_llm: defaultLLM || null,
          theme: localTheme,
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
      </div>

      {/* Закреплённая кнопка сохранения */}
      <div className="sticky bottom-0 pt-6 pb-2 bg-gradient-to-t from-card from-60% to-transparent">
        <Button onClick={handleSave} variant="default2" disabled={saving} className="float-right">
          {saving && <Loader2 className="size-4 mr-2 animate-spin" />}
          Сохранить
        </Button>
      </div>
    </div>
  );
};

export default GeneralSettings;
