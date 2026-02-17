import React, { useCallback, useEffect, useState } from "react";
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
import { apiClient } from "@/lib/api-client";
import type { SearchEngineResponse, SearchEngineTypeMeta } from "./forms/types";

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
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
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

function compactObject(values: Record<string, unknown>): Record<string, unknown> {
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
                  setFieldValue(name, Number.isNaN(parsed) ? undefined : parsed);
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
              <p className="text-xs text-muted-foreground">{property.description}</p>
            )}
          </div>
        );
      })}
    </div>
  );
};

interface SearchEngineItemProps {
  engine: SearchEngineResponse;
  onEdit: (engineId: string) => void;
  onDelete: (engineId: string) => void;
  disabled?: boolean;
}

const SearchEngineItem: React.FC<SearchEngineItemProps> = ({
  engine,
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
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant="outline">{engine.type}</Badge>
        <Badge variant={engine.is_active ? "default" : "secondary"}>
          {engine.is_active ? "Активен" : "Неактивен"}
        </Badge>
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
  isActive: boolean;
  loadingTypes: boolean;
  loadingSchema: boolean;
  saving: boolean;
  submitDisabled: boolean;
  onTypeChange: (type: string) => void;
  onEngineNameChange: (name: string) => void;
  onSettingsChange: (values: Record<string, unknown>) => void;
  onActiveChange: (value: boolean) => void;
  onSubmit: () => void;
  onCancel: () => void;
}

const SearchEngineForm: React.FC<SearchEngineFormProps> = ({
  mode,
  selectedType,
  engineTypes,
  engineName,
  settingsSchema,
  settingsValues,
  isActive,
  loadingTypes,
  loadingSchema,
  saving,
  submitDisabled,
  onTypeChange,
  onEngineNameChange,
  onSettingsChange,
  onActiveChange,
  onSubmit,
  onCancel,
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

      <div className="flex items-center justify-between">
        <Label htmlFor="search-engine-active">Активен</Label>
        <Switch
          id="search-engine-active"
          checked={isActive}
          onCheckedChange={onActiveChange}
          disabled={saving}
        />
      </div>

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
  const [engineTypes, setEngineTypes] = useState<SearchEngineTypeMeta[]>([]);
  const [engines, setEngines] = useState<SearchEngineResponse[]>([]);

  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [editingEngineId, setEditingEngineId] = useState<string | null>(null);

  const [selectedType, setSelectedType] = useState("");
  const [engineName, setEngineName] = useState("");
  const [settingsSchema, setSettingsSchema] = useState<JsonSchema | null>(null);
  const [settingsValues, setSettingsValues] = useState<Record<string, unknown>>({});
  const [isActive, setIsActive] = useState(true);

  const [loadingTypes, setLoadingTypes] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [loadingEngines, setLoadingEngines] = useState(false);
  const [saving, setSaving] = useState(false);

  const fetchEngineTypes = useCallback(async () => {
    setLoadingTypes(true);
    try {
      const data = await apiClient.get<SearchEngineTypeMeta[]>(
        "/api/search-engines/types/meta",
      );
      setEngineTypes(data);
    } catch {
      // Handled globally
    } finally {
      setLoadingTypes(false);
    }
  }, []);

  const fetchEngines = useCallback(async () => {
    setLoadingEngines(true);
    try {
      const data = await apiClient.get<SearchEngineResponse[]>("/api/search-engines");
      setEngines(data);
    } catch {
      // Handled globally
    } finally {
      setLoadingEngines(false);
    }
  }, []);

  useEffect(() => {
    fetchEngineTypes();
    fetchEngines();
  }, [fetchEngineTypes, fetchEngines]);

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
          `/api/search-engines/types/${selectedType}/settings-schema`,
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

  const resetFormState = useCallback(() => {
    setSelectedType("");
    setEngineName("");
    setSettingsSchema(null);
    setSettingsValues({});
    setIsActive(true);
  }, []);

  const handleCreateNew = () => {
    setEditingEngineId(null);
    resetFormState();
    setIsCreatingNew(true);
  };

  const handleStartEdit = (engineId: string) => {
    const engine = engines.find((item) => item.id === engineId);
    if (!engine) return;

    setIsCreatingNew(false);
    setEditingEngineId(engineId);
    setSelectedType(engine.type);
    setEngineName(engine.name || "");
    setSettingsValues(engine.settings || {});
    setIsActive(engine.is_active);
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
    // eslint-disable-next-line no-restricted-globals
    if (!confirm("Вы уверены, что хотите удалить этот search engine?")) return;

    try {
      await apiClient.delete(`/api/search-engines/${engineId}`);
      toast.success("Search engine удален");
      if (editingEngineId === engineId) {
        handleCancelEdit();
      }
      fetchEngines();
    } catch {
      // Handled globally
    }
  };

  const handleSave = async () => {
    if (!selectedType) return;

    setSaving(true);
    try {
      const trimmedName = engineName.trim();

      if (editingEngineId) {
        await apiClient.patch<SearchEngineResponse>(
          `/api/search-engines/${editingEngineId}`,
          {
            name: trimmedName || null,
            settings: compactObject(settingsValues),
            is_active: isActive,
          },
        );
        toast.success("Search engine обновлен");
        handleCancelEdit();
      } else {
        const payload: Record<string, unknown> = {
          type: selectedType,
          settings: compactObject(settingsValues),
          is_active: isActive,
        };

        if (trimmedName) {
          payload.name = trimmedName;
        }

        await apiClient.post<SearchEngineResponse>("/api/search-engines", payload);
        toast.success("Search engine создан");
        handleCancelCreate();
      }

      fetchEngines();
    } catch {
      // Handled globally
    } finally {
      setSaving(false);
    }
  };

  const isEditing = editingEngineId !== null;
  const isSaveDisabled = saving || loadingSchema || !selectedType;

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
        <div className="border border-border rounded-lg p-4 bg-muted/30">
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
            isActive={isActive}
            loadingTypes={loadingTypes}
            loadingSchema={loadingSchema}
            saving={saving}
            submitDisabled={isSaveDisabled}
            onTypeChange={(nextType) => {
              setSelectedType(nextType);
              setSettingsValues({});
            }}
            onEngineNameChange={setEngineName}
            onSettingsChange={setSettingsValues}
            onActiveChange={setIsActive}
            onSubmit={handleSave}
            onCancel={handleCancelCreate}
          />
        </div>
      )}

      <div className="space-y-4">
        {engines.map((engine) => {
          if (editingEngineId === engine.id) {
            return (
              <div
                key={engine.id}
                className="border border-border rounded-lg p-4 bg-muted/30"
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
                  isActive={isActive}
                  loadingTypes={loadingTypes}
                  loadingSchema={loadingSchema}
                  saving={saving}
                  submitDisabled={isSaveDisabled}
                  onTypeChange={() => {
                    // Type is read-only in edit mode.
                  }}
                  onEngineNameChange={setEngineName}
                  onSettingsChange={setSettingsValues}
                  onActiveChange={setIsActive}
                  onSubmit={handleSave}
                  onCancel={handleCancelEdit}
                />
              </div>
            );
          }

          return (
            <SearchEngineItem
              key={engine.id}
              engine={engine}
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
