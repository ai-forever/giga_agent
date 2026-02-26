import React, {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
} from "react";
import { Loader2 } from "lucide-react";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  ConnectorResponse,
  EmbeddingSettings,
  EmbeddingResponse,
  EmbeddingTypeMeta,
  AvailableEmbeddingModel,
  JsonSchema,
  JsonSchemaProperty,
} from "./types";
import { API_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";

type SupportedPropertyType = "string" | "number" | "integer" | "boolean";

function compactObject(
  values: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => value !== undefined),
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
              <Label htmlFor={`embedding-setting-${name}`}>
                {fieldLabel(name, property)}
                {required && <span className="text-destructive ml-1">*</span>}
              </Label>
              <Switch
                id={`embedding-setting-${name}`}
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
              <Label htmlFor={`embedding-setting-${name}`}>
                {fieldLabel(name, property)}
                {required && <span className="text-destructive ml-1">*</span>}
              </Label>
              <Input
                id={`embedding-setting-${name}`}
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

        const value = typeof rawValue === "string" ? rawValue : "";
        return (
          <div key={name} className="space-y-1.5">
            <Label htmlFor={`embedding-setting-${name}`}>
              {fieldLabel(name, property)}
              {required && <span className="text-destructive ml-1">*</span>}
            </Label>
            <Input
              id={`embedding-setting-${name}`}
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

interface EmbeddingFormProps {
  embedding?: EmbeddingResponse;
  onSave: (data: EmbeddingFormSubmitData) => void | Promise<void>;
  onCancel: () => void;
}

export interface EmbeddingFormSubmitData {
  embedding_type: string;
  connector_id: string;
  model_id: string;
  embedding_name?: string;
  embedding_settings: EmbeddingSettings;
  is_active: boolean;
}

export const EmbeddingForm: React.FC<EmbeddingFormProps> = ({
  embedding,
  onSave,
  onCancel,
}) => {
  const [submitting, setSubmitting] = useState(false);
  const [embeddingTypes, setEmbeddingTypes] = useState<EmbeddingTypeMeta[]>([]);
  const [connectors, setConnectors] = useState<ConnectorResponse[]>([]);

  const [selectedEmbeddingType, setSelectedEmbeddingType] = useState<string>(
    embedding?.type || "",
  );
  const [selectedConnectorId, setSelectedConnectorId] = useState<string>(
    embedding?.connector_id || "",
  );

  const [availableModels, setAvailableModels] = useState<
    AvailableEmbeddingModel[]
  >([]);
  const [modelId, setModelId] = useState(embedding?.model_id || "");
  const [embeddingName, setEmbeddingName] = useState(embedding?.name || "");
  const [isActive, setIsActive] = useState(embedding?.is_active ?? true);

  const [settingsSchema, setSettingsSchema] = useState<JsonSchema | null>(null);
  const [settingsValues, setSettingsValues] = useState<Record<string, unknown>>(
    (embedding?.settings as Record<string, unknown>) || {},
  );

  const [loadingEmbeddingTypes, setLoadingEmbeddingTypes] = useState(false);
  const [loadingConnectors, setLoadingConnectors] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [embeddingTypesLoaded, setEmbeddingTypesLoaded] = useState(false);
  const [connectorsLoaded, setConnectorsLoaded] = useState(false);

  const prevModelsKeyRef = useRef<string | null>(null);
  const modelsBySelectionRef = useRef<
    Record<string, AvailableEmbeddingModel[]>
  >({});

  const selectedTypeMeta = useMemo(
    () => embeddingTypes.find((item) => item.type === selectedEmbeddingType),
    [embeddingTypes, selectedEmbeddingType],
  );

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

  const fetchEmbeddingTypes = useCallback(async () => {
    setLoadingEmbeddingTypes(true);
    try {
      const data = await apiClient.get<EmbeddingTypeMeta[]>(
        `${API_PREFIX}/embeddings/types/meta`,
      );
      setEmbeddingTypes(data);
      if (!embedding?.type && data.length > 0) {
        setSelectedEmbeddingType((prev) => prev || data[0].type);
      }
    } catch {
      // handled globally
    } finally {
      setLoadingEmbeddingTypes(false);
      setEmbeddingTypesLoaded(true);
    }
  }, [embedding?.type]);

  const fetchConnectors = useCallback(async () => {
    setLoadingConnectors(true);
    try {
      const data = await apiClient.get<ConnectorResponse[]>(
        `${API_PREFIX}/connectors?only_active=true`,
      );
      setConnectors(data);
    } catch {
      // handled globally
    } finally {
      setLoadingConnectors(false);
      setConnectorsLoaded(true);
    }
  }, []);

  const modelCacheKey = useCallback(
    (embeddingType: string, connectorId: string) =>
      `${embeddingType}:${connectorId}`,
    [],
  );

  const fetchModelsForConnector = useCallback(
    async (connectorId: string, embeddingType: string) => {
      const cacheKey = modelCacheKey(embeddingType, connectorId);
      setLoadingModels(true);
      try {
        const data = await apiClient.get<AvailableEmbeddingModel[]>(
          `${API_PREFIX}/embeddings/models/${connectorId}?embedding_type=${encodeURIComponent(embeddingType)}`,
        );
        const models = Array.isArray(data) ? data : [];
        modelsBySelectionRef.current[cacheKey] = models;
        if (prevModelsKeyRef.current === cacheKey) {
          setAvailableModels(models);
        }
      } catch {
        // handled globally
        modelsBySelectionRef.current[cacheKey] = [];
        if (prevModelsKeyRef.current === cacheKey) {
          setAvailableModels([]);
        }
      } finally {
        if (prevModelsKeyRef.current === cacheKey) {
          setLoadingModels(false);
        }
      }
    },
    [modelCacheKey],
  );

  useEffect(() => {
    fetchEmbeddingTypes();
    fetchConnectors();
  }, [fetchEmbeddingTypes, fetchConnectors]);

  useEffect(() => {
    if (!selectedEmbeddingType) {
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
          `${API_PREFIX}/embeddings/types/${selectedEmbeddingType}/settings-schema`,
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
  }, [selectedEmbeddingType]);

  useEffect(() => {
    if (!selectedConnectorId) {
      setAvailableModels([]);
      setLoadingModels(false);
      return;
    }

    if (!embeddingTypesLoaded || !connectorsLoaded) {
      return;
    }

    const exists = filteredConnectors.some(
      (connector) => connector.id === selectedConnectorId,
    );

    if (!exists) {
      setSelectedConnectorId("");
      setModelId("");
      setAvailableModels([]);
      return;
    }

    const cacheKey = modelCacheKey(selectedEmbeddingType, selectedConnectorId);
    if (prevModelsKeyRef.current !== cacheKey) {
      if (cacheKey in modelsBySelectionRef.current) {
        setAvailableModels(modelsBySelectionRef.current[cacheKey]);
      } else {
        setAvailableModels([]);
        fetchModelsForConnector(selectedConnectorId, selectedEmbeddingType);
      }
      setModelId((prev) =>
        prev &&
        embedding?.connector_id === selectedConnectorId &&
        embedding?.type === selectedEmbeddingType
          ? prev
          : "",
      );
    }

    prevModelsKeyRef.current = cacheKey;
  }, [
    selectedEmbeddingType,
    selectedConnectorId,
    filteredConnectors,
    modelCacheKey,
    fetchModelsForConnector,
    embedding?.connector_id,
    embedding?.type,
    embeddingTypesLoaded,
    connectorsLoaded,
  ]);

  const handleEmbeddingTypeChange = (type: string) => {
    if (embedding) return;
    setSelectedEmbeddingType(type);
    setSelectedConnectorId("");
    setAvailableModels([]);
    modelsBySelectionRef.current = {};
    prevModelsKeyRef.current = null;
    setLoadingModels(false);
    setModelId("");
    setSettingsValues({});
  };

  const handleSubmit = async () => {
    if (!selectedEmbeddingType || !selectedConnectorId || !modelId) return;
    if (submitting) return;
    const embeddingSettings: EmbeddingSettings = compactObject(settingsValues);

    const data: EmbeddingFormSubmitData = {
      embedding_type: selectedEmbeddingType,
      connector_id: selectedConnectorId,
      model_id: modelId,
      embedding_name: embeddingName || undefined,
      embedding_settings: embeddingSettings,
      is_active: isActive,
    };

    setSubmitting(true);
    try {
      await Promise.resolve(onSave(data));
    } finally {
      setSubmitting(false);
    }
  };

  const isSaveDisabled =
    submitting ||
    !selectedEmbeddingType ||
    !selectedConnectorId ||
    !modelId ||
    loadingEmbeddingTypes ||
    loadingConnectors ||
    loadingModels ||
    loadingSchema;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Label htmlFor="embedding-type">Тип Embedding</Label>
        {embedding ? (
          <Input id="embedding-type" value={selectedEmbeddingType} disabled />
        ) : (
          <Select
            value={selectedEmbeddingType}
            onValueChange={handleEmbeddingTypeChange}
            disabled={loadingEmbeddingTypes || submitting}
          >
            <SelectTrigger id="embedding-type" className="w-full">
              {loadingEmbeddingTypes ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Загрузка типов embedding...
                </div>
              ) : (
                <SelectValue placeholder="Выберите тип embedding" />
              )}
            </SelectTrigger>
            <SelectContent>
              {embeddingTypes.map((item) => (
                <SelectItem key={item.type} value={item.type}>
                  {item.type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="embedding-connector-select">Коннектор</Label>
        <Select
          value={selectedConnectorId}
          onValueChange={setSelectedConnectorId}
          disabled={
            submitting ||
            loadingConnectors ||
            !selectedEmbeddingType ||
            filteredConnectors.length === 0
          }
        >
          <SelectTrigger id="embedding-connector-select" className="w-full">
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
            {filteredConnectors.map((item) => (
              <SelectItem key={item.id} value={item.id}>
                {item.name || item.type}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {selectedEmbeddingType &&
          filteredConnectors.length === 0 &&
          !loadingConnectors && (
            <p className="text-sm text-amber-600">
              Нет активных коннекторов для типа{" "}
              <span className="font-medium">{selectedEmbeddingType}</span>.
            </p>
          )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="embedding-model-id">Название модели</Label>
        {availableModels.length > 0 ? (
          <Select
            value={modelId}
            onValueChange={setModelId}
            disabled={submitting || loadingModels}
          >
            <SelectTrigger id="embedding-model-id" className="w-full">
              <SelectValue placeholder="Выберите модель" />
            </SelectTrigger>
            <SelectContent>
              {availableModels.map((model) => (
                <SelectItem key={model.id} value={model.id}>
                  {model.name || model.id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            id="embedding-model-id"
            placeholder="text-embedding-3-small, EmbeddingsGigaR, ..."
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            disabled={submitting}
          />
        )}
        {loadingModels && (
          <p className="text-sm text-muted-foreground">Загрузка моделей...</p>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="embedding-name">
          Отображаемое название (опционально)
        </Label>
        <Input
          id="embedding-name"
          placeholder="Основной embedding"
          value={embeddingName}
          onChange={(e) => setEmbeddingName(e.target.value)}
          disabled={submitting}
        />
      </div>

      <div className="flex items-center justify-between rounded-md border border-border p-3">
        <Label htmlFor="embedding-is-active" className="cursor-pointer">
          Активен
        </Label>
        <Switch
          id="embedding-is-active"
          checked={isActive}
          onCheckedChange={setIsActive}
          disabled={submitting}
        />
      </div>

      {selectedEmbeddingType && (
        <div className="space-y-2">
          <Label>Настройки embedding</Label>
          {loadingSchema ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Загрузка настроек...
            </div>
          ) : (
            <DynamicSettingsForm
              schema={settingsSchema || {}}
              values={settingsValues}
              onChange={setSettingsValues}
              disabled={isSaveDisabled}
            />
          )}
        </div>
      )}

      <div className="flex gap-2 pt-4">
        <Button onClick={handleSubmit} disabled={isSaveDisabled}>
          {submitting ? (
            <>
              <Loader2 className="size-4 animate-spin mr-2" />
              Сохранение...
            </>
          ) : embedding ? (
            "Сохранить"
          ) : (
            "Создать"
          )}
        </Button>
        <Button variant="outline" onClick={onCancel} disabled={submitting}>
          Отмена
        </Button>
      </div>
    </div>
  );
};

export default EmbeddingForm;
