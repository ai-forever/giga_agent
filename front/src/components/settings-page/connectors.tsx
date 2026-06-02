import React, { useCallback, useEffect, useState } from "react";
import { Pencil, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/components/providers/auth.tsx";
import { useConfirm } from "@/components/providers/confirm.tsx";
import ConnectorEditorForm from "./forms/connector-editor-form";
import type { ConnectorResponse } from "./forms/types";

interface ConnectorItemProps {
  connector: ConnectorResponse;
  disabled?: boolean;
  onEdit: (connectorId: string) => void;
  onDelete: (connectorId: string) => void;
}

const ConnectorItem: React.FC<ConnectorItemProps> = ({
  connector,
  disabled,
  onEdit,
  onDelete,
}) => {
  return (
    <div className="flex items-center justify-between p-4 flex-wrap border border-border rounded-lg bg-card hover:bg-accent/50 transition-colors">
      <div className="flex flex-col gap-1">
        <span className="font-medium">{connector.name || connector.type}</span>
        <span className="text-xs text-muted-foreground">
          Тип: {connector.type}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant="outline">{connector.type}</Badge>
        <Badge variant={connector.is_active ? "default" : "secondary"}>
          {connector.is_active ? "Активен" : "Неактивен"}
        </Badge>
        {connector.can_edit && (
          <>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onEdit(connector.id)}
              disabled={disabled}
            >
              <Pencil className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onDelete(connector.id)}
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

export const ConnectorsSettings: React.FC = () => {
  const { user } = useAuth();
  const confirm = useConfirm();
  const canManagePermissions = Boolean(user?.is_superuser);
  const [connectors, setConnectors] = useState<ConnectorResponse[]>([]);

  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [editingConnectorId, setEditingConnectorId] = useState<string | null>(
    null,
  );

  const [loadingConnectors, setLoadingConnectors] = useState(false);

  const fetchConnectors = useCallback(async () => {
    setLoadingConnectors(true);
    try {
      const data = await apiClient.get<ConnectorResponse[]>(
        `${API_AGENT_PREFIX}/connectors`,
      );
      setConnectors(data);
    } catch {
      // handled globally
    } finally {
      setLoadingConnectors(false);
    }
  }, []);

  useEffect(() => {
    fetchConnectors();
  }, [fetchConnectors]);

  const handleCreateNew = () => {
    setEditingConnectorId(null);
    setIsCreatingNew(true);
  };

  const handleStartEdit = (connectorId: string) => {
    const connector = connectors.find((item) => item.id === connectorId);
    if (!connector || !connector.can_edit) return;
    setIsCreatingNew(false);
    setEditingConnectorId(connectorId);
  };

  const handleCancelCreate = () => {
    setIsCreatingNew(false);
  };

  const handleCancelEdit = () => {
    setEditingConnectorId(null);
  };

  const handleDelete = async (connectorId: string) => {
    const connector = connectors.find((item) => item.id === connectorId);
    if (!connector?.can_edit) return;
    if (
      !(await confirm({
        description: "Вы уверены, что хотите удалить этот сервис?",
        variant: "destructive",
      }))
    )
      return;

    try {
      await apiClient.delete(`${API_AGENT_PREFIX}/connectors/${connectorId}`);
      toast.success("Сервис удален");
      if (editingConnectorId === connectorId) {
        handleCancelEdit();
      }
      fetchConnectors();
    } catch {
      // handled globally
    }
  };

  const editingConnector = editingConnectorId
    ? connectors.find((item) => item.id === editingConnectorId)
    : undefined;
  const isBusy = isCreatingNew || editingConnectorId !== null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-medium">Коннекторы</h3>
          <p className="text-sm text-muted-foreground mt-1">
            Управление коннекторами для LLM и генераторов
          </p>
        </div>
        {!isCreatingNew && (
          <Button
            onClick={handleCreateNew}
            size="sm"
            variant="default2"
            disabled={isBusy}
          >
            <Plus className="size-4 mr-2" />
            Добавить
          </Button>
        )}
      </div>

      {isCreatingNew && (
        <div className="border border-border rounded-lg p-4 bg-muted/20">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-medium">Новый сервис</h3>
            <Button variant="ghost" size="icon" onClick={handleCancelCreate}>
              <X className="size-4" />
            </Button>
          </div>

          <ConnectorEditorForm
            mode="create"
            canManagePermissions={canManagePermissions}
            onSaved={() => {
              fetchConnectors();
              setIsCreatingNew(false);
            }}
            onCancel={handleCancelCreate}
          />
        </div>
      )}

      <div className="space-y-4">
        {connectors.map((connector) =>
          editingConnectorId === connector.id ? (
            <div
              key={connector.id}
              className="border border-border rounded-lg p-4 bg-muted/20"
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-medium">
                  Редактирование: {connector.name || connector.type}
                </h3>
                <Button variant="ghost" size="icon" onClick={handleCancelEdit}>
                  <X className="size-4" />
                </Button>
              </div>
              <ConnectorEditorForm
                key={connector.id}
                mode="edit"
                connector={editingConnector}
                canManagePermissions={canManagePermissions}
                onSaved={() => {
                  fetchConnectors();
                  setEditingConnectorId(null);
                }}
                onCancel={handleCancelEdit}
              />
            </div>
          ) : (
            <ConnectorItem
              key={connector.id}
              connector={connector}
              onEdit={handleStartEdit}
              onDelete={handleDelete}
              disabled={isBusy}
            />
          ),
        )}

        {connectors.length === 0 && !loadingConnectors && (
          <p className="text-center text-muted-foreground py-8">
            Нет добавленных сервисов
          </p>
        )}

        {loadingConnectors && (
          <p className="text-center text-muted-foreground py-8">Загрузка...</p>
        )}
      </div>
    </div>
  );
};

export default ConnectorsSettings;
