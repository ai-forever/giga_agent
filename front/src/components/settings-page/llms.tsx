import React, { useState, useEffect, useCallback } from "react";
import { Plus, Pencil, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LLMForm, LLMFormSubmitData } from "./forms/llm";
import type { LLMResponse } from "./forms/types";
import { apiClient } from "@/lib/api-client";

interface LLMItemProps {
  llm: LLMResponse;
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
        <Badge variant="outline">{llm.type}</Badge>
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
  const [llmList, setLlmList] = useState<LLMResponse[]>([]);
  const [loadingLLMs, setLoadingLLMs] = useState(false);
  const [editingLLM, setEditingLLM] = useState<LLMResponse | undefined>();
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [saving, setSaving] = useState(false);

  const fetchLLMs = useCallback(async () => {
    setLoadingLLMs(true);
    try {
      const data = await apiClient.get<LLMResponse[]>("/api/llms");
      setLlmList(data);
    } catch {
      // handled globally
    } finally {
      setLoadingLLMs(false);
    }
  }, []);

  useEffect(() => {
    fetchLLMs();
  }, [fetchLLMs]);

  const handleEditLLM = (llmId: string) => {
    setIsCreatingNew(false);
    setEditingLLM(llmList.find((llm) => llm.id === llmId));
  };

  const handleDeleteLLM = async (llmId: string) => {
    // eslint-disable-next-line no-restricted-globals
    if (!confirm("Вы уверены, что хотите удалить эту модель?")) return;

    try {
      setSaving(true);
      await apiClient.delete(`/api/llms/${llmId}`);
      toast.success("Модель удалена");
      fetchLLMs();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleCreateNew = () => {
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
    if (saving) return;
    try {
      setSaving(true);
      const payload: Record<string, unknown> = {
        type: data.llm_type,
        connector_id: data.connector_id,
        model_id: data.model_id,
        settings: data.llm_settings,
        is_active: data.is_active,
      };
      if (data.llm_name) {
        payload.name = data.llm_name;
      }

      if (!isNewLLM && editingLLM) {
        await apiClient.patch(`/api/llms/${editingLLM.id}`, payload);
        toast.success("Модель обновлена");
        handleCancelEdit();
      } else {
        await apiClient.post("/api/llms", payload);
        toast.success("Модель создана");
        handleCancelCreate();
      }

      fetchLLMs();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
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
          <Button onClick={handleCreateNew} size="sm" variant="default2" disabled={saving}>
            <Plus className="size-4 mr-2" />
            Добавить
          </Button>
        )}
      </div>

      {isCreatingNew && (
        <div className="border border-border rounded-lg p-4 bg-muted/30">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-medium">Новая модель</h3>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleCancelCreate}
              disabled={saving}
            >
              <X className="size-4" />
            </Button>
          </div>
          <LLMForm
            onSave={(data) => handleSaveLLM(data, true)}
            onCancel={handleCancelCreate}
            saving={saving}
          />
        </div>
      )}

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
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={handleCancelEdit}
                  disabled={saving}
                >
                  <X className="size-4" />
                </Button>
              </div>
              <LLMForm
                llm={editingLLM}
                onSave={(data) => handleSaveLLM(data, false)}
                onCancel={handleCancelEdit}
                saving={saving}
              />
            </div>
          ) : (
            <LLMItem
              key={llm.id}
              llm={llm}
              onEdit={handleEditLLM}
              onDelete={handleDeleteLLM}
              disabled={isEditing || saving}
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
