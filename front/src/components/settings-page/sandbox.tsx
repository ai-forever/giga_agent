import React, { useState, useEffect, useCallback } from "react";
import { Loader2, Trash2, Pencil, Save, X, Plus } from "lucide-react";
import { toast } from "sonner";
import { Label } from "@/components/ui/label";
import { Input, SecretInput } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
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
import ResourcePermissions from "./forms/resource-permissions";
import type { ResourcePermissionsDraft } from "./forms/types";
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
  type: string;
  name: string | null;
  settings: Record<string, unknown>;
  idle_timeout: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface JsonSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  anyOf?: { type: string }[];
}

interface JsonSchema {
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
  title?: string;
}

function isSecretField(name: string): boolean {
  const lower = name.toLowerCase();
  return (
    lower.includes("key") ||
    lower.includes("secret") ||
    lower.includes("password") ||
    lower.includes("token")
  );
}

function fieldLabel(name: string, property: JsonSchemaProperty): string {
  if (property.title) return property.title;
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function isFieldRequired(name: string, schema: JsonSchema): boolean {
  return schema.required?.includes(name) ?? false;
}

function isNullable(property: JsonSchemaProperty): boolean {
  if (property.anyOf) {
    return property.anyOf.some((t) => t.type === "null");
  }
  return false;
}

interface SettingsFormProps {
  schema: JsonSchema;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  disabled?: boolean;
}

const SettingsForm: React.FC<SettingsFormProps> = ({
  schema,
  values,
  onChange,
  disabled,
}) => {
  if (!schema.properties) return null;

  const entries = Object.entries(schema.properties);

  const handleFieldChange = (name: string, value: string) => {
    onChange({ ...values, [name]: value || undefined });
  };

  const s3Fields = entries.filter(
    ([name]) => name.startsWith("s3_") || name.startsWith("aws_"),
  );
  const otherFields = entries.filter(
    ([name]) => !name.startsWith("s3_") && !name.startsWith("aws_"),
  );

  const renderField = ([name, property]: [string, JsonSchemaProperty]) => {
    const required = isFieldRequired(name, schema);
    const secret = isSecretField(name);
    const nullable = isNullable(property);
    const value =
      (values[name] as string) ?? (property.default as string) ?? "";
    const InputComponent = secret ? SecretInput : Input;

    return (
      <div key={name} className="space-y-1.5">
        <Label htmlFor={`setting-${name}`}>
          {fieldLabel(name, property)}
          {required && <span className="text-destructive ml-1">*</span>}
          {!required && nullable && (
            <span className="text-muted-foreground ml-1 text-xs font-normal">
              (опционально)
            </span>
          )}
        </Label>
        <InputComponent
          id={`setting-${name}`}
          placeholder={
            property.description ||
            (property.default !== undefined ? String(property.default) : "")
          }
          value={value}
          onChange={(e) => handleFieldChange(name, e.target.value)}
          disabled={disabled}
        />
        {property.description && (
          <p className="text-xs text-muted-foreground">
            {property.description}
          </p>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {otherFields.map(renderField)}

      {s3Fields.length > 0 && (
        <div className="space-y-4 pt-2">
          <div className="flex items-center gap-2">
            <div className="h-px flex-1 bg-border" />
            <span className="text-xs text-muted-foreground">S3 Storage</span>
            <div className="h-px flex-1 bg-border" />
          </div>
          {s3Fields.map(renderField)}
        </div>
      )}
    </div>
  );
};

interface ProviderCardProps {
  provider: SandboxProviderResponse;
  isUserActive: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onActivate: () => void;
  disabled?: boolean;
}

const ProviderCard: React.FC<ProviderCardProps> = ({
  provider,
  isUserActive,
  onEdit,
  onDelete,
  onActivate,
  disabled,
}) => {
  return (
    <div className="flex items-center justify-between p-4 border border-border rounded-lg bg-card hover:bg-accent/50 transition-colors">
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
      </div>
    </div>
  );
};

export const SandboxSettings: React.FC = () => {
  const { user, refreshUser } = useAuth();
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
      // eslint-disable-next-line no-restricted-globals
      !confirm(
        "Вы уверены, что хотите сменить sandbox? Могут возникнуть проблемы со старыми чатами",
      )
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
      if (
        canManagePermissions &&
        hasNonDefaultPermissions(createPermissions)
      ) {
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
    // eslint-disable-next-line no-restricted-globals
    if (!confirm("Вы уверены? Все sandbox'ы этого провайдера будут удалены."))
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
              placeholder="Мой E2B провайдер"
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
            <SettingsForm
              schema={settingsSchema}
              values={settingsValues}
              onChange={setSettingsValues}
              disabled={saving}
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
    </div>
  );
};

export default SandboxSettings;
