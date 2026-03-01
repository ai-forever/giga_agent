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
  ImageGeneratorResponse,
  ImageGeneratorTypeMeta,
  ConnectorResponse,
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

type GeneratorFormMode = "create" | "edit";

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
              <Label htmlFor={`image-gen-setting-${name}`}>
                {fieldLabel(name, property)}
                {required && <span className="text-destructive ml-1">*</span>}
              </Label>
              <Switch
                id={`image-gen-setting-${name}`}
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
              <Label htmlFor={`image-gen-setting-${name}`}>
                {fieldLabel(name, property)}
                {required && <span className="text-destructive ml-1">*</span>}
              </Label>
              <Input
                id={`image-gen-setting-${name}`}
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
            <Label htmlFor={`image-gen-setting-${name}`}>
              {fieldLabel(name, property)}
              {required && <span className="text-destructive ml-1">*</span>}
            </Label>
            <InputComponent
              id={`image-gen-setting-${name}`}
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

interface ImageGeneratorItemProps {
  generator: ImageGeneratorResponse;
  connectorName?: string;
  onEdit: (generatorId: string) => void;
  onDelete: (generatorId: string) => void;
  disabled?: boolean;
}

const ImageGeneratorItem: React.FC<ImageGeneratorItemProps> = ({
  generator,
  connectorName,
  onEdit,
  onDelete,
  disabled,
}) => {
  return (
    <div className="flex items-center justify-between p-4 border border-border rounded-lg bg-card hover:bg-accent/50 transition-colors">
      <div className="flex flex-col gap-1">
        <span className="font-medium">{generator.name || generator.type}</span>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>Тип: {generator.type}</span>
          {connectorName && <span>Connector: {connectorName}</span>}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant="outline">{generator.type}</Badge>
        <Badge variant={generator.is_active ? "default" : "secondary"}>
          {generator.is_active ? "Активен" : "Неактивен"}
        </Badge>
        {generator.can_edit && (
          <>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onEdit(generator.id)}
              disabled={disabled}
            >
              <Pencil className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onDelete(generator.id)}
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

interface ImageGeneratorFormProps {
  mode: GeneratorFormMode;
  selectedType: string;
  generatorTypes: ImageGeneratorTypeMeta[];
  generatorName: string;
  settingsSchema: JsonSchema | null;
  settingsValues: Record<string, unknown>;
  selectedConnectorId: string;
  filteredConnectors: ConnectorResponse[];
  requiresConnector: boolean;
  isActive: boolean;
  loadingTypes: boolean;
  loadingSchema: boolean;
  loadingConnectors: boolean;
  saving: boolean;
  submitDisabled: boolean;
  onTypeChange: (type: string) => void;
  onGeneratorNameChange: (name: string) => void;
  onSettingsChange: (values: Record<string, unknown>) => void;
  onConnectorChange: (connectorId: string) => void;
  onActiveChange: (value: boolean) => void;
  onSubmit: () => void;
  onCancel: () => void;
  permissionsSection?: React.ReactNode;
}

const ImageGeneratorForm: React.FC<ImageGeneratorFormProps> = ({
  mode,
  selectedType,
  generatorTypes,
  generatorName,
  settingsSchema,
  settingsValues,
  selectedConnectorId,
  filteredConnectors,
  requiresConnector,
  isActive,
  loadingTypes,
  loadingSchema,
  loadingConnectors,
  saving,
  submitDisabled,
  onTypeChange,
  onGeneratorNameChange,
  onSettingsChange,
  onConnectorChange,
  onActiveChange,
  onSubmit,
  onCancel,
  permissionsSection,
}) => {
  return (
    <div className="space-y-5">
      <div className="space-y-1.5">
        <Label htmlFor="image-generator-type">
          Тип генератора <span className="text-destructive">*</span>
        </Label>
        {mode === "create" ? (
          <Select
            value={selectedType}
            onValueChange={onTypeChange}
            disabled={loadingTypes || saving}
          >
            <SelectTrigger id="image-generator-type" className="w-full">
              {loadingTypes ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Загрузка типов...
                </div>
              ) : (
                <SelectValue placeholder="Выберите тип генератора" />
              )}
            </SelectTrigger>
            <SelectContent>
              {generatorTypes.map((item) => (
                <SelectItem key={item.type} value={item.type}>
                  {item.type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input id="image-generator-type" value={selectedType} disabled />
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="image-generator-name">
          Название{" "}
          <span className="text-muted-foreground text-xs font-normal">
            (опционально)
          </span>
        </Label>
        <Input
          id="image-generator-name"
          placeholder="Мой генератор"
          value={generatorName}
          onChange={(e) => onGeneratorNameChange(e.target.value)}
          disabled={saving}
        />
      </div>

      {selectedType && (
        <div className="space-y-2">
          <Label>Настройки генератора</Label>
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

      {selectedType && requiresConnector && (
        <div className="space-y-1.5">
          <Label htmlFor="image-generator-connector">
            Коннектор <span className="text-destructive">*</span>
          </Label>
          <Select
            value={selectedConnectorId}
            onValueChange={onConnectorChange}
            disabled={
              loadingConnectors || saving || filteredConnectors.length === 0
            }
          >
            <SelectTrigger id="image-generator-connector" className="w-full">
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

      {selectedType && !requiresConnector && (
        <p className="text-sm text-muted-foreground">
          Для выбранного типа генератора коннектор не требуется.
        </p>
      )}

      <div className="flex items-center justify-between">
        <Label htmlFor="image-generator-active">Активен</Label>
        <Switch
          id="image-generator-active"
          checked={isActive}
          onCheckedChange={onActiveChange}
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

export const ImageGeneratorsSettings: React.FC = () => {
  const { user } = useAuth();
  const canManagePermissions = Boolean(user?.is_superuser);
  const [generatorTypes, setGeneratorTypes] = useState<
    ImageGeneratorTypeMeta[]
  >([]);
  const [connectors, setConnectors] = useState<ConnectorResponse[]>([]);
  const [generators, setGenerators] = useState<ImageGeneratorResponse[]>([]);

  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [editingGeneratorId, setEditingGeneratorId] = useState<string | null>(
    null,
  );

  const [selectedType, setSelectedType] = useState("");
  const [generatorName, setGeneratorName] = useState("");
  const [settingsSchema, setSettingsSchema] = useState<JsonSchema | null>(null);
  const [settingsValues, setSettingsValues] = useState<Record<string, unknown>>(
    {},
  );
  const [selectedConnectorId, setSelectedConnectorId] = useState("");
  const [isActive, setIsActive] = useState(true);

  const [loadingTypes, setLoadingTypes] = useState(false);
  const [loadingConnectors, setLoadingConnectors] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [loadingGenerators, setLoadingGenerators] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadingPermissions, setLoadingPermissions] = useState(false);
  const [createPermissions, setCreatePermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [editPermissions, setEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [initialEditPermissions, setInitialEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);

  const fetchGeneratorTypes = useCallback(async () => {
    setLoadingTypes(true);
    try {
      const data = await apiClient.get<ImageGeneratorTypeMeta[]>(
        `${API_AGENT_PREFIX}/generators/image/types/meta`,
      );
      setGeneratorTypes(data);
    } catch {
      // Handled globally
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
      // Handled globally
    } finally {
      setLoadingConnectors(false);
    }
  }, []);

  const fetchGenerators = useCallback(async () => {
    setLoadingGenerators(true);
    try {
      const data = await apiClient.get<ImageGeneratorResponse[]>(
        `${API_AGENT_PREFIX}/generators/image`,
      );
      setGenerators(data);
    } catch {
      // Handled globally
    } finally {
      setLoadingGenerators(false);
    }
  }, []);

  useEffect(() => {
    fetchGeneratorTypes();
    fetchConnectors();
    fetchGenerators();
  }, [fetchGeneratorTypes, fetchConnectors, fetchGenerators]);

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
          `${API_AGENT_PREFIX}/generators/image/types/${selectedType}/settings-schema`,
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
    () => generatorTypes.find((item) => item.type === selectedType),
    [generatorTypes, selectedType],
  );

  const requiresConnector = selectedTypeMeta?.requires_connector ?? false;
  const supportedConnectorTypes = useMemo(
    () =>
      (selectedTypeMeta?.supported_connector_types || []).map((type) =>
        type.toLowerCase(),
      ),
    [selectedTypeMeta],
  );

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
    setGeneratorName("");
    setSettingsSchema(null);
    setSettingsValues({});
    setSelectedConnectorId("");
    setIsActive(true);
    setCreatePermissions(EMPTY_RESOURCE_PERMISSIONS);
    setEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setInitialEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setLoadingPermissions(false);
  }, []);

  const handleCreateNew = () => {
    setEditingGeneratorId(null);
    resetFormState();
    setIsCreatingNew(true);
  };

  const handleStartEdit = (generatorId: string) => {
    const generator = generators.find((item) => item.id === generatorId);
    if (!generator || !generator.can_edit) return;

    setIsCreatingNew(false);
    setEditingGeneratorId(generatorId);
    setSelectedType(generator.type);
    setGeneratorName(generator.name || "");
    setSettingsValues(generator.settings || {});
    setSelectedConnectorId(generator.connector_id || "");
    setIsActive(generator.is_active);

    if (!canManagePermissions) {
      return;
    }
    setLoadingPermissions(true);
    void apiClient
      .get<ResourcePermissionsDraft>(
        `${API_AGENT_PREFIX}/resource-permissions/image_generator/${generatorId}`,
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
    setEditingGeneratorId(null);
    resetFormState();
  };

  const handleDelete = async (generatorId: string) => {
    const generator = generators.find((item) => item.id === generatorId);
    if (!generator?.can_edit) return;
    // eslint-disable-next-line no-restricted-globals
    if (!confirm("Вы уверены, что хотите удалить этот image generator?"))
      return;

    try {
      await apiClient.delete(
        `${API_AGENT_PREFIX}/generators/image/${generatorId}`,
      );
      toast.success("Image generator удален");
      if (editingGeneratorId === generatorId) {
        handleCancelEdit();
      }
      fetchGenerators();
    } catch {
      // Handled globally
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
      const trimmedName = generatorName.trim();
      const compactedSettings = compactObject(settingsValues);

      if (editingGeneratorId) {
        const currentGenerator = generators.find(
          (item) => item.id === editingGeneratorId,
        );
        if (!currentGenerator) return;

        const isResourceChanged =
          (currentGenerator.name || null) !== (trimmedName || null) ||
          currentGenerator.is_active !== isActive ||
          (currentGenerator.connector_id || null) !==
            (requiresConnector ? selectedConnectorId : null) ||
          stableStringify(currentGenerator.settings || {}) !==
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
        };

        if (requiresConnector) {
          payload.connector_id = selectedConnectorId;
        }

        if (isResourceChanged) {
          await apiClient.patch<ImageGeneratorResponse>(
            `${API_AGENT_PREFIX}/generators/image/${editingGeneratorId}`,
            payload,
          );
        }
        if (isPermissionsChanged) {
          await apiClient.put(
            `${API_AGENT_PREFIX}/resource-permissions/image_generator/${editingGeneratorId}`,
            toPermissionsApiPayload(editPermissions),
          );
        }
        toast.success("Image generator обновлен");
        handleCancelEdit();
      } else {
        const payload: Record<string, unknown> = {
          type: selectedType,
          settings: compactedSettings,
          is_active: isActive,
        };

        if (trimmedName) {
          payload.name = trimmedName;
        }

        if (requiresConnector) {
          payload.connector_id = selectedConnectorId;
        }
        if (
          canManagePermissions &&
          hasNonDefaultPermissions(createPermissions)
        ) {
          payload.permissions = toPermissionsApiPayload(createPermissions);
        }

        await apiClient.post<ImageGeneratorResponse>(
          `${API_AGENT_PREFIX}/generators/image`,
          payload,
        );
        toast.success("Image generator создан");
        handleCancelCreate();
      }

      fetchGenerators();
    } catch {
      // Handled globally
    } finally {
      setSaving(false);
    }
  };

  const isEditing = editingGeneratorId !== null;
  const isSaveDisabled =
    saving ||
    loadingSchema ||
    (Boolean(editingGeneratorId) && canManagePermissions && loadingPermissions) ||
    !selectedType ||
    (requiresConnector &&
      (!selectedConnectorId || filteredConnectors.length === 0));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-medium">Image Generators</h3>
          <p className="text-sm text-muted-foreground mt-1">
            Управление генераторами изображений
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
            <h3 className="font-medium">Новый image generator</h3>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleCancelCreate}
              disabled={saving}
            >
              <X className="size-4" />
            </Button>
          </div>
          <ImageGeneratorForm
            mode="create"
            selectedType={selectedType}
            generatorTypes={generatorTypes}
            generatorName={generatorName}
            settingsSchema={settingsSchema}
            settingsValues={settingsValues}
            selectedConnectorId={selectedConnectorId}
            filteredConnectors={filteredConnectors}
            requiresConnector={requiresConnector}
            isActive={isActive}
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
            onGeneratorNameChange={setGeneratorName}
            onSettingsChange={setSettingsValues}
            onConnectorChange={setSelectedConnectorId}
            onActiveChange={setIsActive}
            onSubmit={handleSave}
            onCancel={handleCancelCreate}
            permissionsSection={
              canManagePermissions ? (
                <ResourcePermissions
                  mode="create"
                  resourceType="image_generator"
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
        {generators.map((generator) => {
          const connector = generator.connector_id
            ? connectorsMap.get(generator.connector_id)
            : undefined;

          if (editingGeneratorId === generator.id) {
            return (
              <div
                key={generator.id}
                className="border border-border rounded-lg p-4 bg-muted/20"
              >
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-medium">
                    Редактирование: {generator.name || generator.type}
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
                <ImageGeneratorForm
                  mode="edit"
                  selectedType={selectedType}
                  generatorTypes={generatorTypes}
                  generatorName={generatorName}
                  settingsSchema={settingsSchema}
                  settingsValues={settingsValues}
                  selectedConnectorId={selectedConnectorId}
                  filteredConnectors={filteredConnectors}
                  requiresConnector={requiresConnector}
                  isActive={isActive}
                  loadingTypes={loadingTypes}
                  loadingSchema={loadingSchema}
                  loadingConnectors={loadingConnectors}
                  saving={saving}
                  submitDisabled={isSaveDisabled}
                  onTypeChange={() => {
                    // Type is read-only in edit mode.
                  }}
                  onGeneratorNameChange={setGeneratorName}
                  onSettingsChange={setSettingsValues}
                  onConnectorChange={setSelectedConnectorId}
                  onActiveChange={setIsActive}
                  onSubmit={handleSave}
                  onCancel={handleCancelEdit}
                  permissionsSection={
                    canManagePermissions ? (
                      <ResourcePermissions
                        mode="edit"
                        resourceType="image_generator"
                        resourceId={editingGeneratorId ?? undefined}
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
            <ImageGeneratorItem
              key={generator.id}
              generator={generator}
              connectorName={
                connector
                  ? connector.name || connector.type
                  : generator.connector_id || undefined
              }
              onEdit={handleStartEdit}
              onDelete={handleDelete}
              disabled={isEditing || saving}
            />
          );
        })}

        {generators.length === 0 && !loadingGenerators && (
          <p className="text-center text-muted-foreground py-8">
            Нет добавленных image generators
          </p>
        )}

        {loadingGenerators && (
          <p className="text-center text-muted-foreground py-8">Загрузка...</p>
        )}
      </div>
    </div>
  );
};

export default ImageGeneratorsSettings;
