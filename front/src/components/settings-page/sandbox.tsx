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

// ============ Types ============

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

// ============ Helpers ============

/** Определяет, является ли поле секретным по имени */
function isSecretField(name: string): boolean {
  const lower = name.toLowerCase();
  return (
    lower.includes("key") ||
    lower.includes("secret") ||
    lower.includes("password") ||
    lower.includes("token")
  );
}

/** Возвращает человеко-читаемый label из имени поля */
function fieldLabel(name: string, property: JsonSchemaProperty): string {
  if (property.title) return property.title;
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Проверяет, является ли поле обязательным */
function isFieldRequired(name: string, schema: JsonSchema): boolean {
  return schema.required?.includes(name) ?? false;
}

/** Определяет, nullable ли поле (anyOf с null) */
function isNullable(property: JsonSchemaProperty): boolean {
  if (property.anyOf) {
    return property.anyOf.some((t) => t.type === "null");
  }
  return false;
}

// ============ Dynamic Settings Form ============

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

  // Группируем S3-поля
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

// ============ Provider Card ============

interface ProviderCardProps {
  provider: SandboxProviderResponse;
  onEdit: () => void;
  onDelete: () => void;
  disabled?: boolean;
}

const ProviderCard: React.FC<ProviderCardProps> = ({
  provider,
  onEdit,
  onDelete,
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
          <Badge variant={provider.is_active ? "default" : "secondary"}>
            {provider.is_active ? "Активен" : "Неактивен"}
          </Badge>
        </div>
        <span className="text-sm text-muted-foreground">
          Idle timeout: {provider.idle_timeout}s
        </span>
      </div>
      <div className="flex items-center gap-2">
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

// ============ Main Component ============

export const SandboxSettings: React.FC = () => {
  // Data state
  const [provider, setProvider] = useState<SandboxProviderResponse | null>(
    null,
  );
  const [providerTypes, setProviderTypes] = useState<string[]>([]);

  // Form state
  const [isCreating, setIsCreating] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [selectedType, setSelectedType] = useState<string>("");
  const [settingsSchema, setSettingsSchema] = useState<JsonSchema | null>(null);
  const [settingsValues, setSettingsValues] = useState<Record<string, unknown>>(
    {},
  );
  const [providerName, setProviderName] = useState("");
  const [idleTimeout, setIdleTimeout] = useState(3600);
  const [isActive, setIsActive] = useState(true);

  // Loading state
  const [loadingProvider, setLoadingProvider] = useState(false);
  const [loadingTypes, setLoadingTypes] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [saving, setSaving] = useState(false);

  // ============ Data Fetching ============

  const fetchProvider = useCallback(async () => {
    setLoadingProvider(true);
    try {
      const data = await apiClient.get<SandboxProviderResponse[]>(
        `${API_AGENT_PREFIX}/sandboxes/providers`,
      );
      setProvider(data.length > 0 ? data[0] : null);
    } catch {
      // Handled globally
    } finally {
      setLoadingProvider(false);
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
      // Handled globally
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

  // Fetch on mount
  useEffect(() => {
    fetchProvider();
    fetchProviderTypes();
  }, [fetchProvider, fetchProviderTypes]);

  // Fetch schema when type changes
  useEffect(() => {
    if (selectedType) {
      fetchSettingsSchema(selectedType);
    } else {
      setSettingsSchema(null);
    }
  }, [selectedType, fetchSettingsSchema]);

  // ============ Form Actions ============

  const resetForm = () => {
    setSelectedType("");
    setSettingsSchema(null);
    setSettingsValues({});
    setProviderName("");
    setIdleTimeout(3600);
    setIsActive(true);
  };

  const handleStartCreate = () => {
    resetForm();
    setIsCreating(true);
    setIsEditing(false);
  };

  const handleStartEdit = () => {
    if (!provider) return;
    setSelectedType(provider.type);
    setSettingsValues(provider.settings);
    setProviderName(provider.name || "");
    setIdleTimeout(provider.idle_timeout);
    setIsActive(provider.is_active);
    setIsCreating(false);
    setIsEditing(true);
  };

  const handleCancel = () => {
    setIsCreating(false);
    setIsEditing(false);
    resetForm();
  };

  const handleCreate = async () => {
    if (!selectedType) return;

    setSaving(true);
    try {
      await apiClient.post(`${API_AGENT_PREFIX}/sandboxes/providers`, {
        type: selectedType,
        name: providerName || null,
        settings: settingsValues,
        idle_timeout: idleTimeout,
        is_active: isActive,
      });
      toast.success("Sandbox провайдер создан");
      setIsCreating(false);
      resetForm();
      fetchProvider();
    } catch {
      // Handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async () => {
    if (!provider) return;

    setSaving(true);
    try {
      await apiClient.patch(
        `${API_AGENT_PREFIX}/sandboxes/providers/${provider.id}`,
        {
          name: providerName || null,
          settings: settingsValues,
          idle_timeout: idleTimeout,
          is_active: isActive,
        },
      );
      toast.success("Sandbox провайдер обновлён");
      setIsEditing(false);
      resetForm();
      fetchProvider();
    } catch {
      // Handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!provider) return;
    if (!confirm("Вы уверены? Все sandbox'ы этого провайдера будут удалены."))
      return;

    try {
      await apiClient.delete(
        `${API_AGENT_PREFIX}/sandboxes/providers/${provider.id}`,
      );
      toast.success("Sandbox провайдер удалён");
      setProvider(null);
      setIsEditing(false);
      resetForm();
    } catch {
      // Handled globally
    }
  };

  // ============ Render ============

  const isFormOpen = isCreating || isEditing;

  if (loadingProvider) {
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
          <h3 className="font-medium">Sandbox провайдер</h3>
          <p className="text-sm text-muted-foreground mt-1">
            Настройте провайдер изолированной среды выполнения
          </p>
        </div>
        {!provider && !isFormOpen && (
          <Button onClick={handleStartCreate} size="sm" variant="default2">
            <Plus className="size-4 mr-2" />
            Добавить
          </Button>
        )}
      </div>

      {/* Existing provider */}
      {provider && !isFormOpen && (
        <ProviderCard
          provider={provider}
          onEdit={handleStartEdit}
          onDelete={handleDelete}
        />
      )}

      {/* No provider placeholder */}
      {!provider && !isFormOpen && (
        <p className="text-center text-muted-foreground py-8">
          Sandbox провайдер не настроен
        </p>
      )}

      {/* Create / Edit form */}
      {isFormOpen && (
        <div className="border border-border rounded-lg p-5 bg-muted/30 space-y-5">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">
              {isCreating ? "Новый провайдер" : "Редактирование провайдера"}
            </h3>
            <Button variant="ghost" size="icon" onClick={handleCancel}>
              <X className="size-4" />
            </Button>
          </div>

          {/* Provider type */}
          <div className="space-y-1.5">
            <Label htmlFor="provider-type">
              Тип провайдера <span className="text-destructive">*</span>
            </Label>
            <Select
              value={selectedType}
              onValueChange={setSelectedType}
              disabled={isEditing || loadingTypes}
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

          {/* Provider name */}
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

          {/* Dynamic settings from schema */}
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

          {/* Idle timeout */}
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

          {/* Active toggle */}
          <div className="flex items-center justify-between">
            <Label htmlFor="is-active">Активен</Label>
            <Switch
              id="is-active"
              checked={isActive}
              onCheckedChange={setIsActive}
              disabled={saving}
            />
          </div>

          {/* Action buttons */}
          <div className="flex gap-2 pt-2">
            <Button
              onClick={isCreating ? handleCreate : handleUpdate}
              disabled={saving || !selectedType}
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
