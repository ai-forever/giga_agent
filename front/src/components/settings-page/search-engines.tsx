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
import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/components/providers/auth.tsx";
import ResourcePermissions from "./forms/resource-permissions";
import type {
  ConnectorResponse,
  SearchEngineResponse,
  SearchEngineTypeMeta,
  ResourcePermissionsDraft,
} from "./forms/types";
import { EMPTY_RESOURCE_PERMISSIONS } from "./forms/types";
import {
  hasNonDefaultPermissions,
  permissionsEqual,
  stableStringify,
  toPermissionsApiPayload,
} from "./forms/resource-permissions-utils";

interface JsonSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  anyOf?: { type?: string }[];
}

interface JsonSchema {
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
}

type SupportedPropertyType = "string" | "number" | "integer" | "boolean";
type SearchEngineFormMode = "create" | "edit";

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

function compactObject(
  values: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => value !== undefined),
  );
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
              <Label htmlFor={`search-engine-setting-${name}`}>
                {fieldLabel(name, property)}
                {required && <span className="text-destructive ml-1">*</span>}
              </Label>
              <Switch
                id={`search-engine-setting-${name}`}
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
              <Label htmlFor={`search-engine-setting-${name}`}>
                {fieldLabel(name, property)}
                {required && <span className="text-destructive ml-1">*</span>}
              </Label>
              <Input
                id={`search-engine-setting-${name}`}
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
            <Label htmlFor={`search-engine-setting-${name}`}>
              {fieldLabel(name, property)}
              {required && <span className="text-destructive ml-1">*</span>}
            </Label>
            <InputComponent
              id={`search-engine-setting-${name}`}
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

interface SearchEngineItemProps {
  engine: SearchEngineResponse;
  connectorName?: string;
  onEdit: (engineId: string) => void;
  onDelete: (engineId: string) => void;
  disabled?: boolean;
}

const SearchEngineItem: React.FC<SearchEngineItemProps> = ({
  engine,
  connectorName,
  onEdit,
  onDelete,
  disabled,
}) => {
  return (
    <div className="flex items-center justify-between p-4 border border-border rounded-lg bg-card hover:bg-accent/50 transition-colors">
      <div className="flex flex-col gap-1">
        <span className="font-medium">{engine.name || engine.type}</span>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>Тип: {engine.type}</span>
          {connectorName && <span>Connector: {connectorName}</span>}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant="outline">{engine.type}</Badge>
        <Badge variant={engine.is_active ? "default" : "secondary"}>
          {engine.is_active ? "Активен" : "Неактивен"}
        </Badge>
        {engine.can_edit && (
          <>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onEdit(engine.id)}
              disabled={disabled}
            >
              <Pencil className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onDelete(engine.id)}
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

interface SearchEngineFormProps {
  mode: SearchEngineFormMode;
  selectedType: string;
  engineTypes: SearchEngineTypeMeta[];
  engineName: string;
  settingsSchema: JsonSchema | null;
  settingsValues: Record<string, unknown>;
  selectedConnectorId: string;
  filteredConnectors: ConnectorResponse[];
  supportsConnectors: boolean;
  requiresConnector: boolean;
  isActive: boolean;
  checkConnection: boolean;
  loadingTypes: boolean;
  loadingSchema: boolean;
  loadingConnectors: boolean;
  saving: boolean;
  submitDisabled: boolean;
  onTypeChange: (type: string) => void;
  onEngineNameChange: (name: string) => void;
  onSettingsChange: (values: Record<string, unknown>) => void;
  onConnectorChange: (connectorId: string) => void;
  onActiveChange: (value: boolean) => void;
  onCheckConnectionChange: (value: boolean) => void;
  onSubmit: () => void;
  onCancel: () => void;
  permissionsSection?: React.ReactNode;
}

const SearchEngineForm: React.FC<SearchEngineFormProps> = ({
  mode,
  selectedType,
  engineTypes,
  engineName,
  settingsSchema,
  settingsValues,
  selectedConnectorId,
  filteredConnectors,
  supportsConnectors,
  requiresConnector,
  isActive,
  checkConnection,
  loadingTypes,
  loadingSchema,
  loadingConnectors,
  saving,
  submitDisabled,
  onTypeChange,
  onEngineNameChange,
  onSettingsChange,
  onConnectorChange,
  onActiveChange,
  onCheckConnectionChange,
  onSubmit,
  onCancel,
  permissionsSection,
}) => {
  return (
    <div className="space-y-5">
      <div className="space-y-1.5">
        <Label htmlFor="search-engine-type">
          Тип движка <span className="text-destructive">*</span>
        </Label>
        {mode === "create" ? (
          <Select
            value={selectedType}
            onValueChange={onTypeChange}
            disabled={loadingTypes || saving}
          >
            <SelectTrigger id="search-engine-type" className="w-full">
              {loadingTypes ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Загрузка типов...
                </div>
              ) : (
                <SelectValue placeholder="Выберите тип движка" />
              )}
            </SelectTrigger>
            <SelectContent>
              {engineTypes.map((item) => (
                <SelectItem key={item.type} value={item.type}>
                  {item.type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input id="search-engine-type" value={selectedType} disabled />
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="search-engine-name">
          Название{" "}
          <span className="text-muted-foreground text-xs font-normal">
            (опционально)
          </span>
        </Label>
        <Input
          id="search-engine-name"
          placeholder="Мой движок"
          value={engineName}
          onChange={(e) => onEngineNameChange(e.target.value)}
          disabled={saving}
        />
      </div>

      {selectedType && (
        <div className="space-y-2">
          <Label>Настройки движка</Label>
          {loadingSchema ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Загрузка настроек...
            </div>
          ) : (
            <SettingsForm
              schema={settingsSchema || {}}
              values={settingsValues}
              onChange={onSettingsChange}
              disabled={saving}
            />
          )}
        </div>
      )}

      {selectedType && supportsConnectors && (
        <div className="space-y-1.5">
          <Label htmlFor="search-engine-connector">
            Коннектор{" "}
            {requiresConnector && <span className="text-destructive">*</span>}
          </Label>
          <Select
            value={selectedConnectorId}
            onValueChange={(value) =>
              onConnectorChange(value === "__none__" ? "" : value)
            }
            disabled={
              loadingConnectors || saving || filteredConnectors.length === 0
            }
          >
            <SelectTrigger id="search-engine-connector" className="w-full">
              {loadingConnectors ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Загрузка коннекторов...
                </div>
              ) : (
                <SelectValue placeholder="Выберите коннектор" />
              )}
            </SelectTrigger>
            <SelectContent>
              {!requiresConnector && (
                <SelectItem value="__none__">Без коннектора</SelectItem>
              )}
              {filteredConnectors.map((connector) => (
                <SelectItem key={connector.id} value={connector.id}>
                  {connector.name || connector.type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {filteredConnectors.length === 0 && !loadingConnectors && (
            <p className="text-sm text-amber-600">
              Нет активных коннекторов для типа{" "}
              <span className="font-medium">{selectedType}</span>.
            </p>
          )}
        </div>
      )}

      {selectedType && !supportsConnectors && (
        <p className="text-sm text-muted-foreground">
          Для выбранного типа движка коннектор не требуется.
        </p>
      )}

      <div className="flex items-center justify-between">
        <Label htmlFor="search-engine-active">Активен</Label>
        <Switch
          id="search-engine-active"
          checked={isActive}
          onCheckedChange={onActiveChange}
          disabled={saving}
        />
      </div>

      <div className="flex items-center justify-between">
        <Label htmlFor="search-engine-check-connection">
          Проверять подключение
        </Label>
        <Switch
          id="search-engine-check-connection"
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

export const SearchEnginesSettings: React.FC = () => {
  const { user } = useAuth();
  const canManagePermissions = Boolean(user?.is_superuser);
  const [engineTypes, setEngineTypes] = useState<SearchEngineTypeMeta[]>([]);
  const [connectors, setConnectors] = useState<ConnectorResponse[]>([]);
  const [engines, setEngines] = useState<SearchEngineResponse[]>([]);

  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [editingEngineId, setEditingEngineId] = useState<string | null>(null);

  const [selectedType, setSelectedType] = useState("");
  const [engineName, setEngineName] = useState("");
  const [settingsSchema, setSettingsSchema] = useState<JsonSchema | null>(null);
  const [settingsValues, setSettingsValues] = useState<Record<string, unknown>>(
    {},
  );
  const [selectedConnectorId, setSelectedConnectorId] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [checkConnection, setCheckConnection] = useState(true);

  const [loadingTypes, setLoadingTypes] = useState(false);
  const [loadingConnectors, setLoadingConnectors] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [loadingEngines, setLoadingEngines] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadingPermissions, setLoadingPermissions] = useState(false);
  const [createPermissions, setCreatePermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [editPermissions, setEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [initialEditPermissions, setInitialEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);

  const fetchEngineTypes = useCallback(async () => {
    setLoadingTypes(true);
    try {
      const data = await apiClient.get<SearchEngineTypeMeta[]>(
        `${API_AGENT_PREFIX}/search-engines/types/meta`,
      );
      setEngineTypes(data);
    } catch {
      // handled globally
    } finally {
      setLoadingTypes(false);
    }
  }, []);

  const fetchConnectors = useCallback(async () => {
    setLoadingConnectors(true);
    try {
      const data = await apiClient.get<ConnectorResponse[]>(
        `${API_AGENT_PREFIX}/connectors?only_active=true`,
      );
      setConnectors(data);
    } catch {
      // handled globally
    } finally {
      setLoadingConnectors(false);
    }
  }, []);

  const fetchEngines = useCallback(async () => {
    setLoadingEngines(true);
    try {
      const data = await apiClient.get<SearchEngineResponse[]>(
        `${API_AGENT_PREFIX}/search-engines`,
      );
      setEngines(data);
    } catch {
      // handled globally
    } finally {
      setLoadingEngines(false);
    }
  }, []);

  useEffect(() => {
    fetchEngineTypes();
    fetchConnectors();
    fetchEngines();
  }, [fetchEngineTypes, fetchConnectors, fetchEngines]);

  useEffect(() => {
    if (!selectedType) {
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
          `${API_AGENT_PREFIX}/search-engines/types/${selectedType}/settings-schema`,
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
  }, [selectedType]);

  const selectedTypeMeta = useMemo(
    () => engineTypes.find((item) => item.type === selectedType),
    [engineTypes, selectedType],
  );

  const requiresConnector = selectedTypeMeta?.requires_connector ?? false;
  const supportedConnectorTypes = useMemo(
    () =>
      (selectedTypeMeta?.supported_connector_types || []).map((type) =>
        type.toLowerCase(),
      ),
    [selectedTypeMeta],
  );
  const supportsConnectors = supportedConnectorTypes.length > 0;

  const filteredConnectors = useMemo(
    () =>
      connectors.filter((connector) =>
        supportedConnectorTypes.includes((connector.type || "").toLowerCase()),
      ),
    [connectors, supportedConnectorTypes],
  );

  useEffect(() => {
    if (!selectedConnectorId) return;
    const exists = filteredConnectors.some(
      (connector) => connector.id === selectedConnectorId,
    );
    if (!exists) {
      setSelectedConnectorId("");
    }
  }, [filteredConnectors, selectedConnectorId]);

  const connectorsMap = useMemo(
    () => new Map(connectors.map((connector) => [connector.id, connector])),
    [connectors],
  );

  const resetFormState = useCallback(() => {
    setSelectedType("");
    setEngineName("");
    setSettingsSchema(null);
    setSettingsValues({});
    setSelectedConnectorId("");
    setIsActive(true);
    setCheckConnection(true);
    setCreatePermissions(EMPTY_RESOURCE_PERMISSIONS);
    setEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setInitialEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setLoadingPermissions(false);
  }, []);

  const handleCreateNew = () => {
    setEditingEngineId(null);
    resetFormState();
    setIsCreatingNew(true);
  };

  const handleStartEdit = (engineId: string) => {
    const engine = engines.find((item) => item.id === engineId);
    if (!engine || !engine.can_edit) return;

    setIsCreatingNew(false);
    setEditingEngineId(engineId);
    setSelectedType(engine.type);
    setEngineName(engine.name || "");
    setSettingsValues(engine.settings || {});
    setSelectedConnectorId(engine.connector_id || "");
    setIsActive(engine.is_active);
    setCheckConnection(true);

    if (!canManagePermissions) {
      return;
    }
    setLoadingPermissions(true);
    void apiClient
      .get<ResourcePermissionsDraft>(
        `${API_AGENT_PREFIX}/resource-permissions/search_engine/${engineId}`,
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
    setEditingEngineId(null);
    resetFormState();
  };

  const handleDelete = async (engineId: string) => {
    const engine = engines.find((item) => item.id === engineId);
    if (!engine?.can_edit) return;
    // eslint-disable-next-line no-restricted-globals
    if (!confirm("Вы уверены, что хотите удалить этот search engine?")) return;

    try {
      await apiClient.delete(`${API_AGENT_PREFIX}/search-engines/${engineId}`);
      toast.success("Search engine удален");
      if (editingEngineId === engineId) {
        handleCancelEdit();
      }
      fetchEngines();
    } catch {
      // handled globally
    }
  };

  const handleSave = async () => {
    if (!selectedType) return;
    if (
      requiresConnector &&
      (!selectedConnectorId || filteredConnectors.length === 0)
    ) {
      return;
    }

    setSaving(true);
    try {
      const trimmedName = engineName.trim();
      const compactedSettings = compactObject(settingsValues);

      if (editingEngineId) {
        const currentEngine = engines.find((item) => item.id === editingEngineId);
        if (!currentEngine) return;

        const isResourceChanged =
          (currentEngine.name || null) !== (trimmedName || null) ||
          currentEngine.is_active !== isActive ||
          (currentEngine.connector_id || null) !==
            (supportsConnectors ? selectedConnectorId || null : null) ||
          stableStringify(currentEngine.settings || {}) !==
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
        if (supportsConnectors) {
          payload.connector_id = selectedConnectorId || null;
        }

        if (isResourceChanged) {
          await apiClient.patch<SearchEngineResponse>(
            `${API_AGENT_PREFIX}/search-engines/${editingEngineId}`,
            payload,
          );
        }
        if (isPermissionsChanged) {
          await apiClient.put(
            `${API_AGENT_PREFIX}/resource-permissions/search_engine/${editingEngineId}`,
            toPermissionsApiPayload(editPermissions),
          );
        }
        toast.success("Search engine обновлен");
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
        if (supportsConnectors && selectedConnectorId) {
          payload.connector_id = selectedConnectorId;
        }
        if (
          canManagePermissions &&
          hasNonDefaultPermissions(createPermissions)
        ) {
          payload.permissions = toPermissionsApiPayload(createPermissions);
        }

        await apiClient.post<SearchEngineResponse>(
          `${API_AGENT_PREFIX}/search-engines`,
          payload,
        );
        toast.success("Search engine создан");
        handleCancelCreate();
      }

      fetchEngines();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const isEditing = editingEngineId !== null;
  const isSaveDisabled =
    saving ||
    loadingSchema ||
    (Boolean(editingEngineId) && canManagePermissions && loadingPermissions) ||
    !selectedType ||
    (requiresConnector &&
      (!selectedConnectorId || filteredConnectors.length === 0));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-medium">Search Engines</h3>
          <p className="text-sm text-muted-foreground mt-1">
            Управление поисковыми движками
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
            <h3 className="font-medium">Новый search engine</h3>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleCancelCreate}
              disabled={saving}
            >
              <X className="size-4" />
            </Button>
          </div>
          <SearchEngineForm
            mode="create"
            selectedType={selectedType}
            engineTypes={engineTypes}
            engineName={engineName}
            settingsSchema={settingsSchema}
            settingsValues={settingsValues}
            selectedConnectorId={selectedConnectorId}
            filteredConnectors={filteredConnectors}
            supportsConnectors={supportsConnectors}
            requiresConnector={requiresConnector}
            isActive={isActive}
            checkConnection={checkConnection}
            loadingTypes={loadingTypes}
            loadingSchema={loadingSchema}
            loadingConnectors={loadingConnectors}
            saving={saving}
            submitDisabled={isSaveDisabled}
            onTypeChange={(nextType) => {
              setSelectedType(nextType);
              setSettingsValues({});
              setSelectedConnectorId("");
            }}
            onEngineNameChange={setEngineName}
            onSettingsChange={setSettingsValues}
            onConnectorChange={setSelectedConnectorId}
            onActiveChange={setIsActive}
            onCheckConnectionChange={setCheckConnection}
            onSubmit={handleSave}
            onCancel={handleCancelCreate}
            permissionsSection={
              canManagePermissions ? (
                <ResourcePermissions
                  mode="create"
                  resourceType="search_engine"
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
        {engines.map((engine) => {
          const connector = engine.connector_id
            ? connectorsMap.get(engine.connector_id)
            : undefined;

          if (editingEngineId === engine.id) {
            return (
              <div
                key={engine.id}
                className="border border-border rounded-lg p-4 bg-muted/20"
              >
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-medium">
                    Редактирование: {engine.name || engine.type}
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
                <SearchEngineForm
                  mode="edit"
                  selectedType={selectedType}
                  engineTypes={engineTypes}
                  engineName={engineName}
                  settingsSchema={settingsSchema}
                  settingsValues={settingsValues}
                  selectedConnectorId={selectedConnectorId}
                  filteredConnectors={filteredConnectors}
                  supportsConnectors={supportsConnectors}
                  requiresConnector={requiresConnector}
                  isActive={isActive}
                  checkConnection={checkConnection}
                  loadingTypes={loadingTypes}
                  loadingSchema={loadingSchema}
                  loadingConnectors={loadingConnectors}
                  saving={saving}
                  submitDisabled={isSaveDisabled}
                  onTypeChange={() => {
                    // Type is read-only in edit mode.
                  }}
                  onEngineNameChange={setEngineName}
                  onSettingsChange={setSettingsValues}
                  onConnectorChange={setSelectedConnectorId}
                  onActiveChange={setIsActive}
                  onCheckConnectionChange={setCheckConnection}
                  onSubmit={handleSave}
                  onCancel={handleCancelEdit}
                  permissionsSection={
                    canManagePermissions ? (
                      <ResourcePermissions
                        mode="edit"
                        resourceType="search_engine"
                        resourceId={editingEngineId ?? undefined}
                        value={editPermissions}
                        onChange={setEditPermissions}
                        canManage={canManagePermissions}
                        disabled={saving || loadingPermissions}
                      />
                    ) : undefined
                  }
                />
              </div>
            );
          }

          return (
            <SearchEngineItem
              key={engine.id}
              engine={engine}
              connectorName={
                connector
                  ? connector.name || connector.type
                  : engine.connector_id || undefined
              }
              onEdit={handleStartEdit}
              onDelete={handleDelete}
              disabled={isEditing || saving}
            />
          );
        })}

        {engines.length === 0 && !loadingEngines && (
          <p className="text-center text-muted-foreground py-8">
            Нет добавленных search engines
          </p>
        )}

        {loadingEngines && (
          <p className="text-center text-muted-foreground py-8">Загрузка...</p>
        )}
      </div>
    </div>
  );
};

export default SearchEnginesSettings;
