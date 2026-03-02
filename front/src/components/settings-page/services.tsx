import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Pencil, Plus, Trash2, X } from "lucide-react";
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
import { ConnectorForm } from "./forms/provider";
import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/components/providers/auth.tsx";
import { useConfirm } from "@/components/providers/confirm.tsx";
import ResourcePermissions from "./forms/resource-permissions";
import type {
  ConnectorResponse,
  ConnectorSettings,
  ConnectorType,
  ConnectorTypeMeta,
  JsonSchema,
  JsonSchemaProperty,
  ResourcePermissionsDraft,
} from "./forms/types";
import { EMPTY_RESOURCE_PERMISSIONS } from "./forms/types";
import {
  hasNonDefaultPermissions,
  permissionsEqual,
  stableStringify,
  toPermissionsApiPayload,
} from "./forms/resource-permissions-utils";

type FormMode = "create" | "edit";
type SupportedPropertyType = "string" | "number" | "integer" | "boolean";

const MANAGED_CONNECTOR_TYPES: ConnectorType[] = ["openai", "gigachat"];
const OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1";

function compactObject(
  values: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => value !== undefined),
  );
}

function isSecretField(name: string): boolean {
  const lower = name.toLowerCase();
  return (
    lower.includes("key") ||
    lower.includes("secret") ||
    lower.includes("password") ||
    lower.includes("token") ||
    lower.includes("credential")
  );
}

function fieldLabel(name: string, property: JsonSchemaProperty): string {
  if (property.title) return property.title;
  return name.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function isFieldRequired(name: string, schema: JsonSchema): boolean {
  return schema.required?.includes(name) ?? false;
}

function resolvePropertyType(
  property: JsonSchemaProperty,
): SupportedPropertyType {
  const directType = property.type;
  if (
    directType === "string" ||
    directType === "number" ||
    directType === "integer" ||
    directType === "boolean"
  ) {
    return directType;
  }

  for (const option of property.anyOf || []) {
    const optionType = option.type;
    if (
      optionType === "string" ||
      optionType === "number" ||
      optionType === "integer" ||
      optionType === "boolean"
    ) {
      return optionType;
    }
  }

  return "string";
}

interface DynamicSettingsFormProps {
  schema: JsonSchema;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  disabled?: boolean;
}

const DynamicSettingsForm: React.FC<DynamicSettingsFormProps> = ({
  schema,
  values,
  onChange,
  disabled,
}) => {
  const entries = Object.entries(schema.properties || {});

  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Для этого типа нет дополнительных настроек.
      </p>
    );
  }

  const setFieldValue = (name: string, value: unknown) => {
    onChange({ ...values, [name]: value });
  };

  return (
    <div className="space-y-4">
      {entries.map(([name, property]) => {
        const propertyType = resolvePropertyType(property);
        const required = isFieldRequired(name, schema);
        const rawValue = values[name] ?? property.default;

        if (propertyType === "boolean") {
          return (
            <div key={name} className="flex items-center justify-between">
              <Label htmlFor={`connector-setting-${name}`}>
                {fieldLabel(name, property)}
                {required && <span className="text-destructive ml-1">*</span>}
              </Label>
              <Switch
                id={`connector-setting-${name}`}
                checked={Boolean(rawValue)}
                onCheckedChange={(checked) => setFieldValue(name, checked)}
                disabled={disabled}
              />
            </div>
          );
        }

        if (propertyType === "number" || propertyType === "integer") {
          const value = typeof rawValue === "number" ? String(rawValue) : "";
          return (
            <div key={name} className="space-y-1.5">
              <Label htmlFor={`connector-setting-${name}`}>
                {fieldLabel(name, property)}
                {required && <span className="text-destructive ml-1">*</span>}
              </Label>
              <Input
                id={`connector-setting-${name}`}
                type="number"
                step={propertyType === "integer" ? 1 : "any"}
                value={value}
                placeholder={
                  property.default !== undefined ? String(property.default) : ""
                }
                onChange={(e) => {
                  const nextValue = e.target.value;
                  if (nextValue === "") {
                    setFieldValue(name, undefined);
                    return;
                  }
                  const parsed =
                    propertyType === "integer"
                      ? parseInt(nextValue, 10)
                      : parseFloat(nextValue);
                  setFieldValue(
                    name,
                    Number.isNaN(parsed) ? undefined : parsed,
                  );
                }}
                disabled={disabled}
              />
              {property.description && (
                <p className="text-xs text-muted-foreground">
                  {property.description}
                </p>
              )}
            </div>
          );
        }

        const InputComponent = isSecretField(name) ? SecretInput : Input;
        const value = typeof rawValue === "string" ? rawValue : "";

        return (
          <div key={name} className="space-y-1.5">
            <Label htmlFor={`connector-setting-${name}`}>
              {fieldLabel(name, property)}
              {required && <span className="text-destructive ml-1">*</span>}
            </Label>
            <InputComponent
              id={`connector-setting-${name}`}
              value={value}
              placeholder={
                property.description ||
                (property.default !== undefined ? String(property.default) : "")
              }
              onChange={(e) => setFieldValue(name, e.target.value || undefined)}
              disabled={disabled}
            />
            {property.description && (
              <p className="text-xs text-muted-foreground">
                {property.description}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
};

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
    <div className="flex items-center justify-between p-4 border border-border rounded-lg bg-card hover:bg-accent/50 transition-colors">
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

interface ConnectorEditorProps {
  mode: FormMode;
  connectorTypes: ConnectorTypeMeta[];
  selectedType: string;
  connectorName: string;
  settingsValues: Record<string, unknown>;
  settingsSchema: JsonSchema | null;
  isActive: boolean;
  checkConnection: boolean;
  loadingTypes: boolean;
  loadingSchema: boolean;
  saving: boolean;
  submitDisabled: boolean;
  onTypeChange: (type: string) => void;
  onConnectorNameChange: (name: string) => void;
  onSettingsChange: (settings: Record<string, unknown>) => void;
  onActiveChange: (active: boolean) => void;
  onCheckConnectionChange: (enabled: boolean) => void;
  onSubmit: () => void;
  onCancel: () => void;
  permissionsSection?: React.ReactNode;
}

const ConnectorEditor: React.FC<ConnectorEditorProps> = ({
  mode,
  connectorTypes,
  selectedType,
  connectorName,
  settingsValues,
  settingsSchema,
  isActive,
  checkConnection,
  loadingTypes,
  loadingSchema,
  saving,
  submitDisabled,
  onTypeChange,
  onConnectorNameChange,
  onSettingsChange,
  onActiveChange,
  onCheckConnectionChange,
  onSubmit,
  onCancel,
  permissionsSection,
}) => {
  const isManagedType = MANAGED_CONNECTOR_TYPES.includes(
    selectedType as ConnectorType,
  );

  return (
    <div className="space-y-5">
      <div className="space-y-1.5">
        <Label htmlFor="connector-type">
          Тип сервиса <span className="text-destructive">*</span>
        </Label>
        {mode === "create" ? (
          <Select
            value={selectedType}
            onValueChange={onTypeChange}
            disabled={loadingTypes || saving}
          >
            <SelectTrigger id="connector-type" className="w-full">
              {loadingTypes ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Загрузка типов...
                </div>
              ) : (
                <SelectValue placeholder="Выберите тип сервиса" />
              )}
            </SelectTrigger>
            <SelectContent>
              {connectorTypes.map((item) => (
                <SelectItem key={item.type} value={item.type}>
                  {item.type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input id="connector-type" value={selectedType} disabled />
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="connector-name">
          Название{" "}
          <span className="text-muted-foreground text-xs font-normal">
            (опционально)
          </span>
        </Label>
        <Input
          id="connector-name"
          placeholder="Мой сервис"
          value={connectorName}
          onChange={(e) => onConnectorNameChange(e.target.value)}
          disabled={saving}
        />
      </div>

      {selectedType && (
        <div className="space-y-2">
          {isManagedType ? (
            <ConnectorForm
              connectorType={selectedType as ConnectorType}
              onConnectorTypeChange={() => {
                // Type is controlled above.
              }}
              showConnectorTypeSelector={false}
              compact
              settings={settingsValues as ConnectorSettings}
              onSettingsChange={(nextSettings) =>
                onSettingsChange(nextSettings as Record<string, unknown>)
              }
            />
          ) : loadingSchema ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Загрузка настроек...
            </div>
          ) : (
            <DynamicSettingsForm
              schema={settingsSchema || {}}
              values={settingsValues}
              onChange={onSettingsChange}
              disabled={saving}
            />
          )}
        </div>
      )}

      <div className="flex items-center justify-between">
        <Label htmlFor="connector-active">Активен</Label>
        <Switch
          id="connector-active"
          checked={isActive}
          onCheckedChange={onActiveChange}
          disabled={saving}
        />
      </div>

      <div className="flex items-center justify-between">
        <Label htmlFor="connector-check-connection">
          Проверять подключение
        </Label>
        <Switch
          id="connector-check-connection"
          checked={checkConnection}
          onCheckedChange={onCheckConnectionChange}
          disabled={saving}
        />
      </div>

      {permissionsSection}

      <div className="flex gap-2 pt-2">
        <Button onClick={onSubmit} disabled={submitDisabled}>
          {saving ? (
            <>
              <Loader2 className="size-4 animate-spin mr-2" />
              Сохранение...
            </>
          ) : mode === "create" ? (
            "Создать"
          ) : (
            "Сохранить"
          )}
        </Button>
        <Button variant="outline" onClick={onCancel} disabled={saving}>
          Отмена
        </Button>
      </div>
    </div>
  );
};

export const ServicesSettings: React.FC = () => {
  const { user } = useAuth();
  const confirm = useConfirm();
  const canManagePermissions = Boolean(user?.is_superuser);
  const [connectors, setConnectors] = useState<ConnectorResponse[]>([]);
  const [connectorTypes, setConnectorTypes] = useState<ConnectorTypeMeta[]>([]);

  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [editingConnectorId, setEditingConnectorId] = useState<string | null>(
    null,
  );

  const [selectedType, setSelectedType] = useState("");
  const [connectorName, setConnectorName] = useState("");
  const [settingsValues, setSettingsValues] = useState<Record<string, unknown>>(
    {},
  );
  const [settingsSchema, setSettingsSchema] = useState<JsonSchema | null>(null);
  const [isActive, setIsActive] = useState(true);
  const [checkConnection, setCheckConnection] = useState(true);

  const [loadingTypes, setLoadingTypes] = useState(false);
  const [loadingConnectors, setLoadingConnectors] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadingPermissions, setLoadingPermissions] = useState(false);
  const [createPermissions, setCreatePermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [editPermissions, setEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [initialEditPermissions, setInitialEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);

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

  const fetchConnectorTypes = useCallback(async () => {
    setLoadingTypes(true);
    try {
      const data = await apiClient.get<ConnectorTypeMeta[]>(
        `${API_AGENT_PREFIX}/connectors/types/meta`,
      );
      setConnectorTypes(data);
    } catch {
      // handled globally
    } finally {
      setLoadingTypes(false);
    }
  }, []);

  useEffect(() => {
    fetchConnectors();
    fetchConnectorTypes();
  }, [fetchConnectors, fetchConnectorTypes]);

  const isManagedType = useMemo(
    () => MANAGED_CONNECTOR_TYPES.includes(selectedType as ConnectorType),
    [selectedType],
  );

  useEffect(() => {
    if (!selectedType || isManagedType) {
      setSettingsSchema(null);
      setLoadingSchema(false);
      return;
    }

    let cancelled = false;
    setLoadingSchema(true);
    setSettingsSchema(null);

    const run = async () => {
      try {
        const schema = await apiClient.get<JsonSchema>(
          `${API_AGENT_PREFIX}/connectors/types/${selectedType}/settings-schema`,
        );
        if (!cancelled) {
          setSettingsSchema(schema);
        }
      } catch {
        if (!cancelled) {
          setSettingsSchema(null);
        }
      } finally {
        if (!cancelled) {
          setLoadingSchema(false);
        }
      }
    };

    run();

    return () => {
      cancelled = true;
    };
  }, [isManagedType, selectedType]);

  const resetFormState = useCallback(() => {
    setSelectedType("");
    setConnectorName("");
    setSettingsValues({});
    setSettingsSchema(null);
    setIsActive(true);
    setCheckConnection(true);
    setCreatePermissions(EMPTY_RESOURCE_PERMISSIONS);
    setEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setInitialEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setLoadingPermissions(false);
  }, []);

  const handleCreateNew = () => {
    setEditingConnectorId(null);
    resetFormState();
    setIsCreatingNew(true);
  };

  const handleStartEdit = (connectorId: string) => {
    const connector = connectors.find((item) => item.id === connectorId);
    if (!connector || !connector.can_edit) return;

    setIsCreatingNew(false);
    setEditingConnectorId(connectorId);
    setSelectedType(connector.type);
    setConnectorName(connector.name || "");
    setSettingsValues((connector.settings || {}) as Record<string, unknown>);
    setIsActive(connector.is_active);
    setCheckConnection(true);

    if (!canManagePermissions) {
      return;
    }

    setLoadingPermissions(true);
    void apiClient
      .get<ResourcePermissionsDraft>(
        `${API_AGENT_PREFIX}/resource-permissions/connector/${connectorId}`,
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

  const handleCancelCreate = () => {
    setIsCreatingNew(false);
    resetFormState();
  };

  const handleCancelEdit = () => {
    setEditingConnectorId(null);
    resetFormState();
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

  const handleSave = async () => {
    if (!selectedType) return;

    setSaving(true);
    try {
      const trimmedName = connectorName.trim();
      const compactedSettings = compactObject(settingsValues);

      if (editingConnectorId) {
        const currentConnector = connectors.find(
          (item) => item.id === editingConnectorId,
        );
        if (!currentConnector) return;

        const isResourceChanged =
          (currentConnector.name || null) !== (trimmedName || null) ||
          currentConnector.is_active !== isActive ||
          stableStringify(currentConnector.settings || {}) !==
            stableStringify(compactedSettings);
        const isPermissionsChanged =
          canManagePermissions &&
          !permissionsEqual(editPermissions, initialEditPermissions);

        if (!isResourceChanged && !isPermissionsChanged) {
          toast.info("Изменений нет");
          return;
        }

        const payload: Record<string, unknown> = {
          name: trimmedName || null,
          settings: compactedSettings,
          is_active: isActive,
          check_connection: checkConnection,
        };

        if (isResourceChanged) {
          await apiClient.patch<ConnectorResponse>(
            `${API_AGENT_PREFIX}/connectors/${editingConnectorId}`,
            payload,
          );
        }

        if (isPermissionsChanged) {
          await apiClient.put(
            `${API_AGENT_PREFIX}/resource-permissions/connector/${editingConnectorId}`,
            toPermissionsApiPayload(editPermissions),
          );
        }

        toast.success("Сервис обновлен");
        handleCancelEdit();
      } else {
        const payload: Record<string, unknown> = {
          type: selectedType,
          settings: compactedSettings,
          is_active: isActive,
          check_connection: checkConnection,
        };

        if (trimmedName) {
          payload.name = trimmedName;
        }
        if (
          canManagePermissions &&
          hasNonDefaultPermissions(createPermissions)
        ) {
          payload.permissions = toPermissionsApiPayload(createPermissions);
        }

        await apiClient.post<ConnectorResponse>(
          `${API_AGENT_PREFIX}/connectors`,
          payload,
        );
        toast.success("Сервис создан");
        handleCancelCreate();
      }

      fetchConnectors();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const isBusy = isCreatingNew || editingConnectorId !== null;
  const isSubmitDisabled =
    saving ||
    !selectedType ||
    (!isManagedType && loadingSchema) ||
    (Boolean(editingConnectorId) && canManagePermissions && loadingPermissions);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-medium">Сервисы</h3>
          <p className="text-sm text-muted-foreground mt-1">
            Управление коннекторами для LLM и генераторов
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
            <h3 className="font-medium">Новый сервис</h3>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleCancelCreate}
              disabled={saving}
            >
              <X className="size-4" />
            </Button>
          </div>

          <ConnectorEditor
            mode="create"
            connectorTypes={connectorTypes}
            selectedType={selectedType}
            connectorName={connectorName}
            settingsValues={settingsValues}
            settingsSchema={settingsSchema}
            isActive={isActive}
            checkConnection={checkConnection}
            loadingTypes={loadingTypes}
            loadingSchema={loadingSchema}
            saving={saving}
            submitDisabled={isSubmitDisabled}
            onTypeChange={(type) => {
              setSelectedType(type);
              setSettingsValues(
                type === "openai" ? { base_url: OPENAI_DEFAULT_BASE_URL } : {},
              );
            }}
            onConnectorNameChange={setConnectorName}
            onSettingsChange={setSettingsValues}
            onActiveChange={setIsActive}
            onCheckConnectionChange={setCheckConnection}
            onSubmit={handleSave}
            onCancel={handleCancelCreate}
            permissionsSection={
              canManagePermissions ? (
                <ResourcePermissions
                  mode="create"
                  resourceType="connector"
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
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={handleCancelEdit}
                  disabled={saving}
                >
                  <X className="size-4" />
                </Button>
              </div>
              <ConnectorEditor
                mode="edit"
                connectorTypes={connectorTypes}
                selectedType={selectedType}
                connectorName={connectorName}
                settingsValues={settingsValues}
                settingsSchema={settingsSchema}
                isActive={isActive}
                checkConnection={checkConnection}
                loadingTypes={loadingTypes}
                loadingSchema={loadingSchema}
                saving={saving}
                submitDisabled={isSubmitDisabled}
                onTypeChange={() => {
                  // Type is read-only in edit mode.
                }}
                onConnectorNameChange={setConnectorName}
                onSettingsChange={setSettingsValues}
                onActiveChange={setIsActive}
                onCheckConnectionChange={setCheckConnection}
                onSubmit={handleSave}
                onCancel={handleCancelEdit}
                permissionsSection={
                  canManagePermissions ? (
                    <ResourcePermissions
                      mode="edit"
                      resourceType="connector"
                      resourceId={editingConnectorId ?? undefined}
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
            <ConnectorItem
              key={connector.id}
              connector={connector}
              onEdit={handleStartEdit}
              onDelete={handleDelete}
              disabled={isBusy || saving}
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

export default ServicesSettings;
