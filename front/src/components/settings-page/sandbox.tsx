import React, { useState, useEffect, useCallback } from "react";
import { Loader2, Trash2, Pencil, Save, X, Plus } from "lucide-react";
import { toast } from "sonner";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/components/providers/auth.tsx";
import { useConfirm } from "@/components/providers/confirm.tsx";
import SchemaFields from "./forms/schema-fields";
import ResourcePermissions from "./forms/resource-permissions";
import type { JsonSchema, ResourcePermissionsDraft } from "./forms/types";
import { EMPTY_RESOURCE_PERMISSIONS } from "./forms/types";
import {
  hasNonDefaultPermissions,
  permissionsEqual,
  stableStringify,
  toPermissionsApiPayload,
} from "./forms/resource-permissions-utils";

interface SandboxProviderResponse {
  id: string;
  owner_id: string;
  can_edit: boolean;
  type: string;
  name: string | null;
  settings: Record<string, unknown>;
  idle_timeout: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface SandboxInstanceResponse {
  id: string;
  provider_id: string;
  owner_id: string;
  owner_email: string | null;
  status: string;
  started_at: string | null;
  stopped_at: string | null;
  can_stop: boolean;
}

function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

interface ProviderCardProps {
  provider: SandboxProviderResponse;
  isUserActive: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onActivate: () => void;
  onOpenSandboxes: () => void;
  disabled?: boolean;
}

const ProviderCard: React.FC<ProviderCardProps> = ({
  provider,
  isUserActive,
  onEdit,
  onDelete,
  onActivate,
  onOpenSandboxes,
  disabled,
}) => {
  return (
    <div className="flex items-center justify-between p-4 flex-wrap border border-border rounded-lg bg-card hover:bg-accent/50 transition-colors">
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="font-medium">
            {provider.name || provider.type.toUpperCase()}
          </span>
          <Badge variant="outline" className="text-xs">
            {provider.type}
          </Badge>
          <Badge variant={isUserActive ? "default" : "secondary"}>
            {isUserActive ? "Активен" : "Неактивен"}
          </Badge>
        </div>
        <span className="text-sm text-muted-foreground">
          Idle timeout: {provider.idle_timeout}s
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onOpenSandboxes}
          disabled={disabled}
        >
          Sandboxes
        </Button>
        {!isUserActive && (
          <Button
            variant="outline"
            size="sm"
            onClick={onActivate}
            disabled={disabled}
          >
            Активировать
          </Button>
        )}
        {provider.can_edit && (
          <>
            <Button
              variant="ghost"
              size="icon"
              onClick={onEdit}
              disabled={disabled}
            >
              <Pencil className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={onDelete}
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

export const SandboxSettings: React.FC = () => {
  const { user, refreshUser } = useAuth();
  const confirm = useConfirm();
  const canManagePermissions = Boolean(user?.is_superuser);
  const [providerList, setProviderList] = useState<SandboxProviderResponse[]>(
    [],
  );
  const [providerTypes, setProviderTypes] = useState<string[]>([]);

  const [isCreating, setIsCreating] = useState(false);
  const [editingProviderId, setEditingProviderId] = useState<string | null>(
    null,
  );
  const [selectedType, setSelectedType] = useState<string>("");
  const [settingsSchema, setSettingsSchema] = useState<JsonSchema | null>(null);
  const [settingsValues, setSettingsValues] = useState<Record<string, unknown>>(
    {},
  );
  const [providerName, setProviderName] = useState("");
  const [idleTimeout, setIdleTimeout] = useState(3600);
  const [isActive, setIsActive] = useState(true);

  const [loadingProviders, setLoadingProviders] = useState(false);
  const [loadingTypes, setLoadingTypes] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sandboxesModalOpen, setSandboxesModalOpen] = useState(false);
  const [sandboxesProvider, setSandboxesProvider] =
    useState<SandboxProviderResponse | null>(null);
  const [providerSandboxes, setProviderSandboxes] = useState<
    SandboxInstanceResponse[]
  >([]);
  const [loadingProviderSandboxes, setLoadingProviderSandboxes] =
    useState(false);
  const [stoppingSandboxId, setStoppingSandboxId] = useState<string | null>(
    null,
  );
  const [loadingPermissions, setLoadingPermissions] = useState(false);
  const [createPermissions, setCreatePermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [editPermissions, setEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [initialEditPermissions, setInitialEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);

  const editingProvider =
    editingProviderId === null
      ? null
      : (providerList.find((item) => item.id === editingProviderId) ?? null);

  const fetchProviders = useCallback(async () => {
    setLoadingProviders(true);
    try {
      const data = await apiClient.get<SandboxProviderResponse[]>(
        `${API_AGENT_PREFIX}/sandboxes/providers`,
      );
      setProviderList(data);
    } catch {
      // handled globally
    } finally {
      setLoadingProviders(false);
    }
  }, []);

  const fetchProviderTypes = useCallback(async () => {
    setLoadingTypes(true);
    try {
      const data = await apiClient.get<string[]>(
        `${API_AGENT_PREFIX}/sandboxes/providers/types`,
      );
      setProviderTypes(data);
    } catch {
      // handled globally
    } finally {
      setLoadingTypes(false);
    }
  }, []);

  const fetchSettingsSchema = useCallback(async (type: string) => {
    setLoadingSchema(true);
    try {
      const data = await apiClient.get<JsonSchema>(
        `${API_AGENT_PREFIX}/sandboxes/providers/types/${type}/settings-schema`,
      );
      setSettingsSchema(data);
    } catch {
      setSettingsSchema(null);
    } finally {
      setLoadingSchema(false);
    }
  }, []);

  const fetchProviderSandboxes = useCallback(async (providerId: string) => {
    setLoadingProviderSandboxes(true);
    try {
      const data = await apiClient.get<SandboxInstanceResponse[]>(
        `${API_AGENT_PREFIX}/sandboxes/providers/${providerId}/sandboxes`,
      );
      setProviderSandboxes(data);
    } catch {
      // handled globally
    } finally {
      setLoadingProviderSandboxes(false);
    }
  }, []);

  useEffect(() => {
    fetchProviders();
    fetchProviderTypes();
  }, [fetchProviders, fetchProviderTypes]);

  useEffect(() => {
    if (selectedType) {
      fetchSettingsSchema(selectedType);
    } else {
      setSettingsSchema(null);
    }
  }, [selectedType, fetchSettingsSchema]);

  const resetForm = () => {
    setSelectedType("");
    setSettingsSchema(null);
    setSettingsValues({});
    setProviderName("");
    setIdleTimeout(3600);
    setIsActive(true);
    setCreatePermissions(EMPTY_RESOURCE_PERMISSIONS);
    setEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setInitialEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setLoadingPermissions(false);
  };

  const handleStartCreate = () => {
    resetForm();
    setEditingProviderId(null);
    setIsCreating(true);
  };

  const handleStartEdit = (provider: SandboxProviderResponse) => {
    if (!provider.can_edit) return;
    setSelectedType(provider.type);
    setSettingsValues(provider.settings);
    setProviderName(provider.name || "");
    setIdleTimeout(provider.idle_timeout);
    setIsActive(provider.is_active);
    setEditingProviderId(provider.id);
    setIsCreating(false);

    if (!canManagePermissions) {
      return;
    }
    setLoadingPermissions(true);
    void apiClient
      .get<ResourcePermissionsDraft>(
        `${API_AGENT_PREFIX}/resource-permissions/sandbox/${provider.id}`,
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

  const handleCancel = () => {
    setIsCreating(false);
    setEditingProviderId(null);
    resetForm();
  };

  const handleActivate = async (providerId: string) => {
    if (saving || user?.sandbox_provider_id === providerId) return;

    if (
      user?.sandbox_provider_id &&
      !(await confirm({
        variant: "destructive",
        description:
          "Вы уверены, что хотите сменить sandbox? Могут возникнуть проблемы со старыми чатами",
      }))
    ) {
      return;
    }

    try {
      setSaving(true);
      await apiClient.patch(`${API_AGENT_PREFIX}/auth/users/me`, {
        sandbox_provider_id: providerId,
      });
      await refreshUser();
      toast.success("Sandbox провайдер активирован");
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleCreate = async () => {
    if (!selectedType) return;

    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        type: selectedType,
        name: providerName || null,
        settings: settingsValues,
        idle_timeout: idleTimeout,
        is_active: isActive,
      };
      if (canManagePermissions && hasNonDefaultPermissions(createPermissions)) {
        payload.permissions = toPermissionsApiPayload(createPermissions);
      }
      await apiClient.post(`${API_AGENT_PREFIX}/sandboxes/providers`, payload);
      toast.success("Sandbox провайдер создан");
      setIsCreating(false);
      resetForm();
      await fetchProviders();
      await refreshUser();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async () => {
    if (!editingProvider) return;

    setSaving(true);
    try {
      const nextName = providerName || null;
      const nextSettings = settingsValues;
      const nextIdleTimeout = idleTimeout;
      const nextIsActive = isActive;
      const hasResourceChanges =
        (editingProvider.name || null) !== nextName ||
        editingProvider.idle_timeout !== nextIdleTimeout ||
        editingProvider.is_active !== nextIsActive ||
        stableStringify(editingProvider.settings || {}) !==
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
          `${API_AGENT_PREFIX}/sandboxes/providers/${editingProvider.id}`,
          {
            name: nextName,
            settings: nextSettings,
            idle_timeout: nextIdleTimeout,
            is_active: nextIsActive,
          },
        );
      }
      if (hasPermissionsChanges) {
        await apiClient.put(
          `${API_AGENT_PREFIX}/resource-permissions/sandbox/${editingProvider.id}`,
          toPermissionsApiPayload(editPermissions),
        );
      }
      toast.success("Sandbox провайдер обновлён");
      setEditingProviderId(null);
      resetForm();
      await fetchProviders();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (providerId: string) => {
    const provider = providerList.find((item) => item.id === providerId);
    if (!provider?.can_edit) return;
    if (
      !(await confirm({
        description:
          "Вы уверены? Все sandbox'ы этого провайдера будут удалены.",
        variant: "destructive",
      }))
    )
      return;

    try {
      setSaving(true);
      await apiClient.delete(
        `${API_AGENT_PREFIX}/sandboxes/providers/${providerId}`,
      );
      toast.success("Sandbox провайдер удалён");
      if (editingProviderId === providerId) {
        setEditingProviderId(null);
        resetForm();
      }
      await fetchProviders();
      await refreshUser();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleOpenSandboxes = (provider: SandboxProviderResponse) => {
    setSandboxesProvider(provider);
    setProviderSandboxes([]);
    setStoppingSandboxId(null);
    setSandboxesModalOpen(true);
    void fetchProviderSandboxes(provider.id);
  };

  const handleSandboxesModalChange = (open: boolean) => {
    setSandboxesModalOpen(open);
    if (!open) {
      setSandboxesProvider(null);
      setProviderSandboxes([]);
      setStoppingSandboxId(null);
      setLoadingProviderSandboxes(false);
    }
  };

  const handleStopSandbox = async (sandbox: SandboxInstanceResponse) => {
    if (!sandboxesProvider || stoppingSandboxId) return;
    setStoppingSandboxId(sandbox.id);
    try {
      const updated = await apiClient.post<SandboxInstanceResponse>(
        `${API_AGENT_PREFIX}/sandboxes/providers/${sandboxesProvider.id}/sandboxes/${sandbox.id}/stop`,
        {},
      );
      setProviderSandboxes((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      );
      toast.success("Sandbox остановлен");
    } catch {
      // handled globally
    } finally {
      setStoppingSandboxId(null);
    }
  };

  const isFormOpen = isCreating || editingProviderId !== null;

  if (loadingProviders) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-medium">Sandbox провайдеры</h3>
          <p className="text-sm text-muted-foreground mt-1">
            Настройте и активируйте провайдер изолированной среды выполнения
          </p>
        </div>
        {!isFormOpen && (
          <Button onClick={handleStartCreate} size="sm" variant="default2">
            <Plus className="size-4 mr-2" />
            Добавить
          </Button>
        )}
      </div>

      {!isFormOpen && (
        <div className="space-y-4">
          {providerList.map((provider) => (
            <ProviderCard
              key={provider.id}
              provider={provider}
              isUserActive={user?.sandbox_provider_id === provider.id}
              onActivate={() => handleActivate(provider.id)}
              onEdit={() => handleStartEdit(provider)}
              onDelete={() => handleDelete(provider.id)}
              onOpenSandboxes={() => handleOpenSandboxes(provider)}
              disabled={saving}
            />
          ))}
          {providerList.length === 0 && (
            <p className="text-center text-muted-foreground py-8">
              Sandbox провайдеры не настроены
            </p>
          )}
        </div>
      )}

      {isFormOpen && (
        <div className="border border-border rounded-lg p-5 bg-muted/20 space-y-5">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">
              {isCreating ? "Новый провайдер" : "Редактирование провайдера"}
            </h3>
            <Button variant="ghost" size="icon" onClick={handleCancel}>
              <X className="size-4" />
            </Button>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="provider-type">
              Тип провайдера <span className="text-destructive">*</span>
            </Label>
            <Select
              value={selectedType}
              onValueChange={setSelectedType}
              disabled={!isCreating || loadingTypes}
            >
              <SelectTrigger id="provider-type" className="w-full">
                {loadingTypes ? (
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" />
                    Загрузка...
                  </div>
                ) : (
                  <SelectValue placeholder="Выберите тип провайдера" />
                )}
              </SelectTrigger>
              <SelectContent>
                {providerTypes.map((type) => (
                  <SelectItem key={type} value={type}>
                    {type.toUpperCase()}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="provider-name">
              Название{" "}
              <span className="text-muted-foreground text-xs font-normal">
                (опционально)
              </span>
            </Label>
            <Input
              id="provider-name"
              placeholder="Название провайдера"
              value={providerName}
              onChange={(e) => setProviderName(e.target.value)}
              disabled={saving}
            />
          </div>

          {loadingSchema && (
            <div className="flex items-center gap-2 text-muted-foreground py-2">
              <Loader2 className="size-4 animate-spin" />
              Загрузка настроек...
            </div>
          )}

          {settingsSchema && !loadingSchema && (
            <SchemaFields
              schema={settingsSchema}
              values={settingsValues}
              onChange={setSettingsValues}
              disabled={saving}
              idPrefix="setting"
              groups={[
                {
                  id: "main",
                  match: (name) =>
                    !name.startsWith("s3_") && !name.startsWith("aws_"),
                },
                {
                  id: "s3",
                  title: "S3 Storage",
                  separator: true,
                  match: (name) =>
                    name.startsWith("s3_") || name.startsWith("aws_"),
                },
              ]}
            />
          )}

          <div className="space-y-1.5">
            <Label htmlFor="idle-timeout">Idle Timeout (секунды)</Label>
            <Input
              id="idle-timeout"
              type="number"
              min={60}
              placeholder="3600"
              value={idleTimeout}
              onChange={(e) =>
                setIdleTimeout(parseInt(e.target.value, 10) || 3600)
              }
              disabled={saving}
            />
            <p className="text-xs text-muted-foreground">
              Время простоя до автоматической остановки sandbox
            </p>
          </div>

          <div className="flex items-center justify-between">
            <Label htmlFor="is-active">Активен</Label>
            <Switch
              id="is-active"
              checked={isActive}
              onCheckedChange={setIsActive}
              disabled={saving}
            />
          </div>

          {canManagePermissions && (
            <ResourcePermissions
              mode={isCreating ? "create" : "edit"}
              resourceType="sandbox"
              resourceId={editingProviderId ?? undefined}
              value={isCreating ? createPermissions : editPermissions}
              onChange={isCreating ? setCreatePermissions : setEditPermissions}
              canManage={canManagePermissions}
              disabled={saving || loadingPermissions}
            />
          )}

          <div className="flex gap-2 pt-2">
            <Button
              onClick={isCreating ? handleCreate : handleUpdate}
              disabled={
                saving ||
                !selectedType ||
                (!isCreating && canManagePermissions && loadingPermissions)
              }
            >
              {saving ? (
                <>
                  <Loader2 className="size-4 animate-spin mr-2" />
                  Сохранение...
                </>
              ) : (
                <>
                  <Save className="size-4 mr-2" />
                  {isCreating ? "Создать" : "Сохранить"}
                </>
              )}
            </Button>
            <Button variant="outline" onClick={handleCancel} disabled={saving}>
              Отмена
            </Button>
          </div>
        </div>
      )}

      <Dialog
        open={sandboxesModalOpen}
        onOpenChange={handleSandboxesModalChange}
      >
        <DialogContent className="sandboxes-modal w-[900px] min-h-0 max-h-[85vh] overflow-hidden sm:max-w-6xl grid-rows-[auto_1fr]">
          <DialogHeader>
            <DialogTitle>
              Sandboxes:{" "}
              {sandboxesProvider
                ? sandboxesProvider.name || sandboxesProvider.type.toUpperCase()
                : ""}
            </DialogTitle>
            <DialogDescription>
              Список sandbox'ов провайдера и управление running-инстансами
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 overflow-auto">
            {loadingProviderSandboxes ? (
              <div className="flex items-center justify-center py-10 text-muted-foreground">
                <Loader2 className="size-5 animate-spin mr-2" />
                Загрузка sandbox'ов...
              </div>
            ) : providerSandboxes.length === 0 ? (
              <p className="text-sm text-muted-foreground py-6">
                Sandbox'ы не найдены
              </p>
            ) : (
              <Table className="table-fixed">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[38%]">Юзер</TableHead>
                    <TableHead className="w-[38%]">
                      Когда запущен или остановлен
                    </TableHead>
                    <TableHead className="w-[12%] min-w-[120px]">
                      Статус
                    </TableHead>
                    <TableHead className="w-[12%] min-w-[120px] text-right">
                      Действие
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {providerSandboxes.map((item) => {
                    const isRunning = item.status === "running";
                    const canRenderStopAction =
                      item.can_stop &&
                      ["starting", "running", "stopping", "error"].includes(
                        item.status,
                      );
                    const owner = item.owner_email || item.owner_id;
                    return (
                      <TableRow key={item.id}>
                        <TableCell
                          className="max-w-[520px] truncate"
                          title={owner}
                        >
                          {owner}
                        </TableCell>
                        <TableCell className="min-w-[240px]">
                          {formatDateTime(
                            isRunning ? item.started_at : item.stopped_at,
                          )}
                        </TableCell>
                        <TableCell className="min-w-[120px]">
                          <Badge
                            variant={
                              isRunning
                                ? "default"
                                : item.status === "stopped"
                                  ? "secondary"
                                  : "outline"
                            }
                          >
                            {item.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right min-w-[120px]">
                          {canRenderStopAction ? (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleStopSandbox(item)}
                              disabled={stoppingSandboxId !== null}
                            >
                              {stoppingSandboxId === item.id ? (
                                <>
                                  <Loader2 className="size-4 animate-spin mr-2" />
                                  Stop...
                                </>
                              ) : (
                                "Stop"
                              )}
                            </Button>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default SandboxSettings;
