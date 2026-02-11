import React, { useState, useEffect, useCallback } from "react";
import { Plus, Pencil, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { LLMForm, LLMFormSubmitData } from "./forms/llm";
import type {
  LLMResponse,
  ProviderResponse,
  LLMWithProviderResponse,
} from "./forms/types";
import { apiClient } from "@/lib/api-client";

interface LLMListItem extends LLMResponse {
  provider?: ProviderResponse;
}

interface LLMItemProps {
  llm: LLMListItem;
  onEdit: (llmId: string) => void;
  onDelete: (llmId: string) => void;
  disabled?: boolean;
}

const LLMItem: React.FC<LLMItemProps> = ({
  llm,
  onEdit,
  onDelete,
  disabled,
}) => {
  return (
    <div className="flex items-center justify-between p-4 border border-border rounded-lg bg-card hover:bg-accent/50 transition-colors">
      <div className="flex flex-col">
        <span className="font-medium">{llm.name || llm.model_id}</span>
        <span className="text-sm text-muted-foreground">{llm.model_id}</span>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant={llm.is_active ? "default" : "secondary"}>
          {llm.is_active ? "Активна" : "Неактивна"}
        </Badge>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onEdit(llm.id)}
          disabled={disabled}
        >
          <Pencil className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onDelete(llm.id)}
          disabled={disabled}
        >
          <Trash2 className="size-4 text-destructive" />
        </Button>
      </div>
    </div>
  );
};

export const LLMSettings: React.FC = () => {
  const [llmList, setLlmList] = useState<LLMListItem[]>([]);
  const [loadingLLMs, setLoadingLLMs] = useState(false);
  const [editingLLM, setEditingLLM] = useState<LLMResponse | undefined>();
  const [isCreatingNew, setIsCreatingNew] = useState(false);

  const fetchLLMs = useCallback(async () => {
    setLoadingLLMs(true);
    try {
      const data = await apiClient.get<LLMResponse[]>("/api/llms");
      setLlmList(data);
    } catch {
    } finally {
      setLoadingLLMs(false);
    }
  }, []);

  useEffect(() => {
    fetchLLMs();
  }, [fetchLLMs]);

  const handleEditLLM = async (llmId: string) => {
    // Закрываем форму создания при редактировании
    setIsCreatingNew(false);

    setEditingLLM(llmList.find((llm) => llm.id === llmId));
  };

  const handleDeleteLLM = async (llmId: string) => {
    // eslint-disable-next-line no-restricted-globals
    if (!confirm("Вы уверены, что хотите удалить эту модель?")) return;

    try {
      await apiClient.delete(`/api/llms/${llmId}`);
      toast.success("Модель удалена");
      fetchLLMs();
    } catch {}
  };

  const handleCreateNew = () => {
    // Закрываем редактирование при создании новой
    setEditingLLM(undefined);
    setIsCreatingNew(true);
  };

  const handleCancelEdit = () => {
    setEditingLLM(undefined);
  };

  const handleCancelCreate = () => {
    setIsCreatingNew(false);
  };

  const handleSaveLLM = async (data: LLMFormSubmitData, isNewLLM: boolean) => {
    try {
      if (!isNewLLM && editingLLM) {
        // Update existing LLM
        // API логика:
        // - provider_id указан → переключиться на провайдера (и обновить если есть другие поля)
        // - provider_type указан (без provider_id) → создать нового провайдера
        // - ничего не указано → обновить текущего провайдера
        const updatePayload: Record<string, unknown> = {
          model_id: data.model_id,
          llm_name: data.llm_name,
          llm_settings: data.llm_settings,
          is_active: data.is_active,
        };

        // Передаём provider_id если выбран существующий провайдер
        if (data.provider_id) {
          updatePayload.provider_id = data.provider_id;
        }
        // Передаём данные провайдера для создания/обновления
        if (data.provider_type) {
          updatePayload.provider_type = data.provider_type;
        }
        if (data.provider_name) {
          updatePayload.provider_name = data.provider_name;
        }
        if (data.provider_settings) {
          updatePayload.provider_settings = data.provider_settings;
        }

        await apiClient.patch(`/api/llms/${editingLLM.id}`, updatePayload);
        toast.success("Модель обновлена");
        handleCancelEdit();
        fetchLLMs();
      } else {
        // Create new LLM
        // API логика:
        // - provider_id + данные провайдера → провайдер обновляется
        // - только provider_id → используется существующий провайдер
        // - только provider_type → создаётся новый провайдер
        const createPayload: Record<string, unknown> = {
          model_id: data.model_id,
          llm_name: data.llm_name,
          llm_settings: data.llm_settings,
          is_active: data.is_active,
        };

        // Передаём provider_id если выбран существующий провайдер
        if (data.provider_id) {
          createPayload.provider_id = data.provider_id;
        }
        // Передаём данные провайдера для создания/обновления
        if (data.provider_type) {
          createPayload.provider_type = data.provider_type;
        }
        if (data.provider_name) {
          createPayload.provider_name = data.provider_name;
        }
        if (data.provider_settings) {
          createPayload.provider_settings = data.provider_settings;
        }

        await apiClient.post("/api/llms", createPayload);
        toast.success("Модель создана");
        handleCancelCreate();
        fetchLLMs();
      }
    } catch {
      // Ошибка уже обработана глобально
    }
  };

  const isEditing = editingLLM !== undefined;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-medium">Настройки LLM</h3>
          <p className="text-sm text-muted-foreground mt-1">
            Управление языковыми моделями
          </p>
        </div>
        {!isCreatingNew && (
          <Button onClick={handleCreateNew} size="sm" variant={"default2"}>
            <Plus className="size-4 mr-2" />
            Добавить
          </Button>
        )}
      </div>

      {/* Форма создания новой LLM сверху списка */}
      {isCreatingNew && (
        <div className="border border-border rounded-lg p-4 bg-muted/30">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-medium">Новая модель</h3>
            <Button variant="ghost" size="icon" onClick={handleCancelCreate}>
              <X className="size-4" />
            </Button>
          </div>
          <LLMForm
            onSave={(data) => handleSaveLLM(data, true)}
            onCancel={handleCancelCreate}
          />
        </div>
      )}

      {/* Список LLM */}
      <div className="space-y-4">
        {llmList.map((llm) =>
          editingLLM && editingLLM.id === llm.id ? (
            <div
              key={llm.id}
              className="border border-border rounded-lg p-4 bg-muted/30"
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-medium">
                  Редактирование: {llm.name || llm.model_id}
                </h3>
                <Button variant="ghost" size="icon" onClick={handleCancelEdit}>
                  <X className="size-4" />
                </Button>
              </div>
              <LLMForm
                llm={editingLLM}
                onSave={(data) => handleSaveLLM(data, false)}
                onCancel={handleCancelEdit}
              />
            </div>
          ) : (
            <LLMItem
              key={llm.id}
              llm={llm}
              onEdit={handleEditLLM}
              onDelete={handleDeleteLLM}
              disabled={isEditing}
            />
          ),
        )}
        {llmList.length === 0 && !loadingLLMs && (
          <p className="text-center text-muted-foreground py-8">
            Нет добавленных моделей
          </p>
        )}
        {loadingLLMs && (
          <p className="text-center text-muted-foreground py-8">Загрузка...</p>
        )}
      </div>
    </div>
  );
};

export default LLMSettings;
