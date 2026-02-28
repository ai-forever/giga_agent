import React, { useState, useEffect, useCallback } from "react";
import { Plus, Pencil, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmbeddingForm, EmbeddingFormSubmitData } from "./forms/embedding";
import type {
  EmbeddingResponse,
  ResourcePermissionsDraft,
} from "./forms/types";
import { EMPTY_RESOURCE_PERMISSIONS } from "./forms/types";
import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/components/providers/auth.tsx";
import ResourcePermissions from "./forms/resource-permissions";
import {
  hasNonDefaultPermissions,
  permissionsEqual,
  stableStringify,
  toPermissionsApiPayload,
} from "./forms/resource-permissions-utils";

interface EmbeddingItemProps {
  embedding: EmbeddingResponse;
  isUserActive: boolean;
  onEdit: (embeddingId: string) => void;
  onDelete: (embeddingId: string) => void;
  onActivate: (embeddingId: string) => void;
  disabled?: boolean;
}

const EmbeddingItem: React.FC<EmbeddingItemProps> = ({
  embedding,
  isUserActive,
  onEdit,
  onDelete,
  onActivate,
  disabled,
}) => {
  return (
    <div className="flex items-center justify-between p-4 border border-border rounded-lg bg-card hover:bg-accent/50 transition-colors">
      <div className="flex flex-col">
        <span className="font-medium">
          {embedding.name || embedding.model_id}
        </span>
        <span className="text-sm text-muted-foreground">
          {embedding.model_id}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant="outline">{embedding.type}</Badge>
        <Badge variant={isUserActive ? "default" : "secondary"}>
          {isUserActive ? "Активен" : "Неактивен"}
        </Badge>
        {!isUserActive && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => onActivate(embedding.id)}
            disabled={disabled}
          >
            Активировать
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onEdit(embedding.id)}
          disabled={disabled}
        >
          <Pencil className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => onDelete(embedding.id)}
          disabled={disabled}
        >
          <Trash2 className="size-4 text-destructive" />
        </Button>
      </div>
    </div>
  );
};

export const EmbeddingsSettings: React.FC = () => {
  const { user, refreshUser } = useAuth();
  const canManagePermissions = Boolean(user?.is_superuser);
  const [embeddingList, setEmbeddingList] = useState<EmbeddingResponse[]>([]);
  const [loadingEmbeddings, setLoadingEmbeddings] = useState(false);
  const [editingEmbedding, setEditingEmbedding] = useState<
    EmbeddingResponse | undefined
  >();
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadingPermissions, setLoadingPermissions] = useState(false);
  const [createPermissions, setCreatePermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [editPermissions, setEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [initialEditPermissions, setInitialEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);

  const fetchEmbeddings = useCallback(async () => {
    setLoadingEmbeddings(true);
    try {
      const data = await apiClient.get<EmbeddingResponse[]>(
        `${API_AGENT_PREFIX}/embeddings`,
      );
      setEmbeddingList(data);
    } catch {
      // handled globally
    } finally {
      setLoadingEmbeddings(false);
    }
  }, []);

  useEffect(() => {
    fetchEmbeddings();
  }, [fetchEmbeddings]);

  const handleEditEmbedding = (embeddingId: string) => {
    setIsCreatingNew(false);
    const embedding = embeddingList.find((item) => item.id === embeddingId);
    setEditingEmbedding(embedding);
    if (!embedding || !canManagePermissions) {
      setEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
      setInitialEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
      setLoadingPermissions(false);
      return;
    }
    setLoadingPermissions(true);
    void apiClient
      .get<ResourcePermissionsDraft>(
        `${API_AGENT_PREFIX}/resource-permissions/embedding/${embeddingId}`,
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

  const handleDeleteEmbedding = async (embeddingId: string) => {
    // eslint-disable-next-line no-restricted-globals
    if (!confirm("Вы уверены, что хотите удалить эту embedding модель?"))
      return;

    try {
      setSaving(true);
      await apiClient.delete(`${API_AGENT_PREFIX}/embeddings/${embeddingId}`);
      toast.success("Embedding модель удалена");
      fetchEmbeddings();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleCreateNew = () => {
    setEditingEmbedding(undefined);
    setIsCreatingNew(true);
    setCreatePermissions(EMPTY_RESOURCE_PERMISSIONS);
  };

  const handleCancelEdit = () => {
    setEditingEmbedding(undefined);
    setEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setInitialEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setLoadingPermissions(false);
  };

  const handleCancelCreate = () => {
    setIsCreatingNew(false);
    setCreatePermissions(EMPTY_RESOURCE_PERMISSIONS);
  };

  const handleSaveEmbedding = async (
    data: EmbeddingFormSubmitData,
    isNewEmbedding: boolean,
  ) => {
    if (saving) return;
    try {
      setSaving(true);
      const nextType = data.embedding_type;
      const nextConnectorId = data.connector_id;
      const nextModelId = data.model_id;
      const nextIsActive = data.is_active;
      const nextName = data.embedding_name ?? null;
      const nextSettings = data.embedding_settings;
      const payload: Record<string, unknown> = {
        type: nextType,
        connector_id: nextConnectorId,
        model_id: nextModelId,
        settings: nextSettings,
        is_active: nextIsActive,
      };
      if (data.embedding_name) {
        payload.name = data.embedding_name;
      }

      if (!isNewEmbedding && editingEmbedding) {
        const hasResourceChanges =
          editingEmbedding.type !== nextType ||
          editingEmbedding.connector_id !== nextConnectorId ||
          editingEmbedding.model_id !== nextModelId ||
          (editingEmbedding.name || null) !== nextName ||
          editingEmbedding.is_active !== nextIsActive ||
          stableStringify(editingEmbedding.settings || {}) !==
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
            `${API_AGENT_PREFIX}/embeddings/${editingEmbedding.id}`,
            payload,
          );
        }
        if (hasPermissionsChanges) {
          await apiClient.put(
            `${API_AGENT_PREFIX}/resource-permissions/embedding/${editingEmbedding.id}`,
            toPermissionsApiPayload(editPermissions),
          );
        }

        toast.success("Embedding модель обновлена");
        handleCancelEdit();
      } else {
        if (
          canManagePermissions &&
          hasNonDefaultPermissions(createPermissions)
        ) {
          payload.permissions = toPermissionsApiPayload(createPermissions);
        }
        await apiClient.post(`${API_AGENT_PREFIX}/embeddings`, payload);
        toast.success("Embedding модель создана");
        handleCancelCreate();
      }

      fetchEmbeddings();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleActivateEmbedding = async (embeddingId: string) => {
    if (saving || user?.embedding_id === embeddingId) return;
    if (
      user?.embedding_id &&
      // eslint-disable-next-line no-restricted-globals
      !confirm(
        "Вы уверены, что хотите сменить эмбединги? Вы не сможете работать со старыми RAG-документами",
      )
    ) {
      return;
    }
    try {
      setSaving(true);
      await apiClient.patch(`${API_AGENT_PREFIX}/auth/users/me`, {
        embedding_id: embeddingId,
      });
      await refreshUser();
      await fetchEmbeddings();
      toast.success("Embedding модель активирована");
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const isEditing = editingEmbedding !== undefined;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-medium">Настройки Embeddings</h3>
          <p className="text-sm text-muted-foreground mt-1">
            Управление embedding моделями
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
            <h3 className="font-medium">Новая embedding модель</h3>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleCancelCreate}
              disabled={saving}
            >
              <X className="size-4" />
            </Button>
          </div>
          <EmbeddingForm
            onSave={(data) => handleSaveEmbedding(data, true)}
            onCancel={handleCancelCreate}
            permissionsSection={
              canManagePermissions ? (
                <ResourcePermissions
                  mode="create"
                  resourceType="embedding"
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
        {embeddingList.map((embedding) =>
          editingEmbedding && editingEmbedding.id === embedding.id ? (
            <div
              key={embedding.id}
              className="border border-border rounded-lg p-4 bg-muted/20"
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-medium">
                  Редактирование: {embedding.name || embedding.model_id}
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
              <EmbeddingForm
                embedding={editingEmbedding}
                onSave={(data) => handleSaveEmbedding(data, false)}
                onCancel={handleCancelEdit}
                permissionsSection={
                  canManagePermissions ? (
                    <ResourcePermissions
                      mode="edit"
                      resourceType="embedding"
                      resourceId={editingEmbedding.id}
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
            <EmbeddingItem
              key={embedding.id}
              embedding={embedding}
              isUserActive={user?.embedding_id === embedding.id}
              onEdit={handleEditEmbedding}
              onDelete={handleDeleteEmbedding}
              onActivate={handleActivateEmbedding}
              disabled={isEditing || saving}
            />
          ),
        )}
        {embeddingList.length === 0 && !loadingEmbeddings && (
          <p className="text-center text-muted-foreground py-8">
            Нет добавленных embedding моделей
          </p>
        )}
        {loadingEmbeddings && (
          <p className="text-center text-muted-foreground py-8">Загрузка...</p>
        )}
      </div>
    </div>
  );
};

export default EmbeddingsSettings;
