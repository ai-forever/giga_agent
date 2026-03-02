import React, { useState, useEffect, useCallback } from "react";
import { Plus, Pencil, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LLMForm, LLMFormSubmitData } from "./forms/llm";
import type { LLMResponse, ResourcePermissionsDraft } from "./forms/types";
import { EMPTY_RESOURCE_PERMISSIONS } from "./forms/types";
import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/components/providers/auth.tsx";
import { useConfirm } from "@/components/providers/confirm.tsx";
import ResourcePermissions from "./forms/resource-permissions";
import {
  hasNonDefaultPermissions,
  permissionsEqual,
  stableStringify,
  toPermissionsApiPayload,
} from "./forms/resource-permissions-utils";

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
        {llm.can_edit && (
          <>
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
          </>
        )}
      </div>
    </div>
  );
};

export const LLMSettings: React.FC = () => {
  const { user } = useAuth();
  const confirm = useConfirm();
  const canManagePermissions = Boolean(user?.is_superuser);
  const [llmList, setLlmList] = useState<LLMResponse[]>([]);
  const [loadingLLMs, setLoadingLLMs] = useState(false);
  const [editingLLM, setEditingLLM] = useState<LLMResponse | undefined>();
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadingPermissions, setLoadingPermissions] = useState(false);
  const [createPermissions, setCreatePermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [editPermissions, setEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [initialEditPermissions, setInitialEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);

  const fetchLLMs = useCallback(async () => {
    setLoadingLLMs(true);
    try {
      const data = await apiClient.get<LLMResponse[]>(
        `${API_AGENT_PREFIX}/llms`,
      );
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
    const llm = llmList.find((item) => item.id === llmId);
    if (!llm?.can_edit) return;
    setEditingLLM(llm);
    if (!llm || !canManagePermissions) {
      setEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
      setInitialEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
      setLoadingPermissions(false);
      return;
    }
    setLoadingPermissions(true);
    void apiClient
      .get<ResourcePermissionsDraft>(
        `${API_AGENT_PREFIX}/resource-permissions/llm/${llmId}`,
      )
      .then((permissions) => {
        setEditPermissions(permissions);
        setInitialEditPermissions(permissions);
      })
      .catch(() => {
        setEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
        setInitialEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
      })
      .finally(() => {
        setLoadingPermissions(false);
      });
  };

  const handleDeleteLLM = async (llmId: string) => {
    const llm = llmList.find((item) => item.id === llmId);
    if (!llm?.can_edit) return;
    if (
      !(await confirm({
        description: "Вы уверены, что хотите удалить эту модель?",
        variant: "destructive",
      }))
    )
      return;

    try {
      setSaving(true);
      await apiClient.delete(`${API_AGENT_PREFIX}/llms/${llmId}`);
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
    setCreatePermissions(EMPTY_RESOURCE_PERMISSIONS);
  };

  const handleCancelEdit = () => {
    setEditingLLM(undefined);
    setEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setInitialEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setLoadingPermissions(false);
  };

  const handleCancelCreate = () => {
    setIsCreatingNew(false);
    setCreatePermissions(EMPTY_RESOURCE_PERMISSIONS);
  };

  const handleSaveLLM = async (data: LLMFormSubmitData, isNewLLM: boolean) => {
    if (saving) return;
    try {
      setSaving(true);
      const nextType = data.llm_type;
      const nextConnectorId = data.connector_id;
      const nextModelId = data.model_id;
      const nextIsActive = data.is_active;
      const nextName = data.llm_name ?? null;
      const nextSettings = data.llm_settings;
      const payload: Record<string, unknown> = {
        type: nextType,
        connector_id: nextConnectorId,
        model_id: nextModelId,
        settings: nextSettings,
        is_active: nextIsActive,
        check_connection: data.check_connection,
      };
      if (data.llm_name) {
        payload.name = data.llm_name;
      }

      if (!isNewLLM && editingLLM) {
        const hasResourceChanges =
          editingLLM.type !== nextType ||
          editingLLM.connector_id !== nextConnectorId ||
          editingLLM.model_id !== nextModelId ||
          (editingLLM.name || null) !== nextName ||
          editingLLM.is_active !== nextIsActive ||
          stableStringify(editingLLM.settings || {}) !==
            stableStringify(nextSettings);
        const hasPermissionsChanges =
          canManagePermissions &&
          !permissionsEqual(editPermissions, initialEditPermissions);

        if (!hasResourceChanges && !hasPermissionsChanges) {
          toast.info("Изменений нет");
          return;
        }

        if (hasResourceChanges) {
          await apiClient.patch(
            `${API_AGENT_PREFIX}/llms/${editingLLM.id}`,
            payload,
          );
        }
        if (hasPermissionsChanges) {
          await apiClient.put(
            `${API_AGENT_PREFIX}/resource-permissions/llm/${editingLLM.id}`,
            toPermissionsApiPayload(editPermissions),
          );
        }

        toast.success("Модель обновлена");
        handleCancelEdit();
      } else {
        if (
          canManagePermissions &&
          hasNonDefaultPermissions(createPermissions)
        ) {
          payload.permissions = toPermissionsApiPayload(createPermissions);
        }
        await apiClient.post(`${API_AGENT_PREFIX}/llms`, payload);
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
          <Button
            onClick={handleCreateNew}
            size="sm"
            variant="default2"
            disabled={saving}
          >
            <Plus className="size-4 mr-2" />
            Добавить
          </Button>
        )}
      </div>

      {isCreatingNew && (
        <div className="border border-border rounded-lg p-4 bg-muted/20">
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
            permissionsSection={
              canManagePermissions ? (
                <ResourcePermissions
                  mode="create"
                  resourceType="llm"
                  value={createPermissions}
                  onChange={setCreatePermissions}
                  canManage={canManagePermissions}
                  disabled={saving}
                />
              ) : undefined
            }
          />
        </div>
      )}

      <div className="space-y-4">
        {llmList.map((llm) =>
          editingLLM && editingLLM.id === llm.id ? (
            <div
              key={llm.id}
              className="border border-border rounded-lg p-4 bg-muted/20"
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
                permissionsSection={
                  canManagePermissions ? (
                    <ResourcePermissions
                      mode="edit"
                      resourceType="llm"
                      resourceId={editingLLM.id}
                      value={editPermissions}
                      onChange={setEditPermissions}
                      canManage={canManagePermissions}
                      disabled={saving || loadingPermissions}
                    />
                  ) : undefined
                }
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
