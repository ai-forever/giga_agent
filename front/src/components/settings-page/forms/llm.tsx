import React, {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
} from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type {
  ConnectorResponse,
  AvailableModel,
  LLMSettings,
  LLMResponse,
  LLMTypeMeta,
  JsonSchema,
} from "./types";
import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/components/providers/auth.tsx";
import SchemaFields from "./schema-fields";
import ConnectorSelect from "./connector-select";
import { compactObject } from "./schema-fields-utils";

interface LLMFormProps {
  llm?: LLMResponse;
  onSave: (data: LLMFormSubmitData) => void;
  onCancel: () => void;
  saving?: boolean;
  permissionsSection?: React.ReactNode;
}

export interface LLMFormSubmitData {
  connector_id: string;
  llm_type: string;
  model_id: string;
  llm_name?: string;
  llm_settings: LLMSettings;
  is_active: boolean;
  check_connection: boolean;
}

export const LLMForm: React.FC<LLMFormProps> = ({
  llm,
  onSave,
  onCancel,
  saving = false,
  permissionsSection,
}) => {
  const { user } = useAuth();
  const canManagePermissions = Boolean(user?.is_superuser);
  const [llmTypes, setLlmTypes] = useState<LLMTypeMeta[]>([]);
  const [connectors, setConnectors] = useState<ConnectorResponse[]>([]);

  const [selectedLLMType, setSelectedLLMType] = useState<string>(
    llm?.type || "",
  );
  const [selectedConnectorId, setSelectedConnectorId] = useState<string>(
    llm?.connector_id || "",
  );

  const [availableModels, setAvailableModels] = useState<AvailableModel[]>([]);
  const [modelId, setModelId] = useState(llm?.model_id || "");
  const [llmName, setLlmName] = useState(llm?.name || "");
  const [isActive, setIsActive] = useState(llm?.is_active ?? true);
  const [checkConnection, setCheckConnection] = useState(true);

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [temperature, setTemperature] = useState<number>(
    llm?.settings?.temperature ?? 0.7,
  );
  const [tempInput, setTempInput] = useState<string>(
    String(llm?.settings?.temperature ?? 0.7),
  );
  const [settingsSchema, setSettingsSchema] = useState<JsonSchema | null>(null);
  const [settingsValues, setSettingsValues] = useState<Record<string, unknown>>(
    (llm?.settings as Record<string, unknown>) || {},
  );

  const [loadingLLMTypes, setLoadingLLMTypes] = useState(false);
  const [loadingConnectors, setLoadingConnectors] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [llmTypesLoaded, setLlmTypesLoaded] = useState(false);
  const [connectorsLoaded, setConnectorsLoaded] = useState(false);

  const prevModelsKeyRef = useRef<string | null>(null);
  const modelsBySelectionRef = useRef<Record<string, AvailableModel[]>>({});

  const selectedTypeMeta = useMemo(
    () => llmTypes.find((item) => item.type === selectedLLMType),
    [llmTypes, selectedLLMType],
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
  const usesDynamicSettings = !["openai", "gigachat"].includes(
    selectedLLMType.toLowerCase(),
  );

  const fetchLLMTypes = useCallback(async () => {
    setLoadingLLMTypes(true);
    try {
      const data = await apiClient.get<LLMTypeMeta[]>(
        `${API_AGENT_PREFIX}/llms/types/meta`,
      );
      setLlmTypes(data);
      if (!llm?.type && data.length > 0) {
        setSelectedLLMType((prev) => prev || data[0].type);
      }
    } catch {
      // handled globally
    } finally {
      setLoadingLLMTypes(false);
      setLlmTypesLoaded(true);
    }
  }, [llm?.type]);

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
      setConnectorsLoaded(true);
    }
  }, []);

  const modelCacheKey = useCallback(
    (llmType: string, connectorId: string) => `${llmType}:${connectorId}`,
    [],
  );

  const fetchModelsForConnector = useCallback(
    async (connectorId: string, llmType: string) => {
      const cacheKey = modelCacheKey(llmType, connectorId);
      setLoadingModels(true);
      try {
        const data = await apiClient.get<AvailableModel[]>(
          `${API_AGENT_PREFIX}/llms/models/${connectorId}?llm_type=${encodeURIComponent(llmType)}`,
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
    fetchLLMTypes();
    fetchConnectors();
  }, [fetchLLMTypes, fetchConnectors]);

  useEffect(() => {
    if (!selectedLLMType || !usesDynamicSettings) {
      setSettingsSchema(null);
      setLoadingSchema(false);
      if (!llm) {
        setSettingsValues({});
      }
      return;
    }

    let cancelled = false;
    setLoadingSchema(true);
    setSettingsSchema(null);

    const run = async () => {
      try {
        const schema = await apiClient.get<JsonSchema>(
          `${API_AGENT_PREFIX}/llms/types/${selectedLLMType}/settings-schema`,
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
  }, [selectedLLMType, usesDynamicSettings, llm]);

  useEffect(() => {
    if (!selectedConnectorId) {
      setAvailableModels([]);
      setLoadingModels(false);
      return;
    }

    if (!llmTypesLoaded || !connectorsLoaded) {
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

    const cacheKey = modelCacheKey(selectedLLMType, selectedConnectorId);
    if (prevModelsKeyRef.current !== cacheKey) {
      if (cacheKey in modelsBySelectionRef.current) {
        setAvailableModels(modelsBySelectionRef.current[cacheKey]);
      } else {
        setAvailableModels([]);
        fetchModelsForConnector(selectedConnectorId, selectedLLMType);
      }
      setModelId((prev) =>
        prev &&
        llm?.connector_id === selectedConnectorId &&
        llm?.type === selectedLLMType
          ? prev
          : "",
      );
    }

    prevModelsKeyRef.current = cacheKey;
  }, [
    selectedLLMType,
    selectedConnectorId,
    filteredConnectors,
    modelCacheKey,
    fetchModelsForConnector,
    llm?.connector_id,
    llm?.type,
    llmTypesLoaded,
    connectorsLoaded,
  ]);

  const handleLLMTypeChange = (type: string) => {
    if (llm) return;
    setSelectedLLMType(type);
    setSelectedConnectorId("");
    setAvailableModels([]);
    modelsBySelectionRef.current = {};
    prevModelsKeyRef.current = null;
    setLoadingModels(false);
    setModelId("");
    setSettingsValues({});
  };

  const handleTemperatureSliderChange = (values: number[]) => {
    const value = values[0];
    setTemperature(value);
    setTempInput(value.toFixed(2));
  };

  const handleTemperatureInputChange = (
    e: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const value = e.target.value;
    setTempInput(value);
    const num = parseFloat(value);
    if (!isNaN(num) && num >= 0 && num <= 1) {
      setTemperature(num);
    }
  };

  const handleTemperatureInputBlur = () => {
    const num = parseFloat(tempInput);
    if (isNaN(num) || num < 0) {
      setTemperature(0);
      setTempInput("0");
    } else if (num > 1) {
      setTemperature(1);
      setTempInput("1");
    } else {
      setTemperature(num);
      setTempInput(num.toFixed(2));
    }
  };

  const handleSubmit = () => {
    if (!selectedLLMType || !selectedConnectorId) return;

    const data: LLMFormSubmitData = {
      llm_type: selectedLLMType,
      connector_id: selectedConnectorId,
      model_id: modelId,
      llm_name: llmName || undefined,
      llm_settings: usesDynamicSettings
        ? (compactObject(settingsValues) as LLMSettings)
        : {
            temperature,
          },
      is_active: isActive,
      check_connection: checkConnection,
    };

    onSave(data);
  };

  const isSaveDisabled =
    saving ||
    !selectedLLMType ||
    !selectedConnectorId ||
    !modelId ||
    loadingLLMTypes ||
    loadingConnectors ||
    loadingModels ||
    loadingSchema;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Label htmlFor="llm-type">Тип LLM</Label>
        {llm ? (
          <Input id="llm-type" value={selectedLLMType} disabled />
        ) : (
          <Select
            value={selectedLLMType}
            onValueChange={handleLLMTypeChange}
            disabled={loadingLLMTypes || saving}
          >
            <SelectTrigger id="llm-type" className="w-full">
              {loadingLLMTypes ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Загрузка типов LLM...
                </div>
              ) : (
                <SelectValue placeholder="Выберите тип LLM" />
              )}
            </SelectTrigger>
            <SelectContent>
              {llmTypes.map((item) => (
                <SelectItem key={item.type} value={item.type}>
                  {item.type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="connector-select">Коннектор</Label>
        <ConnectorSelect
          id="connector-select"
          value={selectedConnectorId}
          onValueChange={setSelectedConnectorId}
          allowedTypes={supportedConnectorTypes}
          disabled={saving || !selectedLLMType}
          loading={loadingConnectors}
          connectors={connectors}
          onConnectorsChanged={fetchConnectors}
          canManagePermissions={canManagePermissions}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="model-id">Название модели</Label>
        {availableModels.length > 0 ? (
          <Select
            value={modelId}
            onValueChange={setModelId}
            disabled={saving || loadingModels}
          >
            <SelectTrigger id="model-id" className="w-full">
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
            id="model-id"
            placeholder="gpt-4o, gpt-4o-mini, ..."
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            disabled={saving}
          />
        )}
        {loadingModels && (
          <p className="text-sm text-muted-foreground">Загрузка моделей...</p>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="llm-name">Отображаемое название (опционально)</Label>
        <Input
          id="llm-name"
          placeholder="Мой GPT-4"
          value={llmName}
          onChange={(e) => setLlmName(e.target.value)}
          disabled={saving}
        />
      </div>

      <div className="flex items-center justify-between rounded-md border border-border p-3">
        <Label htmlFor="llm-check-connection" className="cursor-pointer">
          Проверять подключение
        </Label>
        <Switch
          id="llm-check-connection"
          checked={checkConnection}
          onCheckedChange={setCheckConnection}
          disabled={saving}
        />
      </div>

      {!usesDynamicSettings && (
        <Collapsible open={showAdvanced} onOpenChange={setShowAdvanced}>
          <CollapsibleTrigger asChild>
            <button className="flex items-center gap-2 w-full py-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
              <div className="flex-1 h-px bg-border" />
              <span className="flex items-center gap-1">
                Дополнительные настройки
                <ChevronDown
                  className={`size-4 transition-transform ${showAdvanced ? "rotate-180" : ""}`}
                />
              </span>
              <div className="flex-1 h-px bg-border" />
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent className="space-y-4 pt-4">
            <div className="space-y-3">
              <Label>Температура</Label>
              <div className="flex items-center gap-4">
                <div className="flex-1">
                  <Slider
                    value={[temperature]}
                    onValueChange={handleTemperatureSliderChange}
                    min={0}
                    max={1}
                    step={0.01}
                    disabled={saving}
                  />
                </div>
                <Input
                  type="number"
                  className="w-20"
                  min={0}
                  max={1}
                  step={0.01}
                  value={tempInput}
                  onChange={handleTemperatureInputChange}
                  onBlur={handleTemperatureInputBlur}
                  disabled={saving}
                />
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}

      {usesDynamicSettings && selectedLLMType && (
        <div className="space-y-2">
          <Label>Настройки LLM</Label>
          {loadingSchema ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Загрузка настроек...
            </div>
          ) : (
            <SchemaFields
              schema={settingsSchema || {}}
              values={settingsValues}
              onChange={setSettingsValues}
              disabled={saving}
              idPrefix="llm-setting"
            />
          )}
        </div>
      )}

      {permissionsSection}

      <div className="flex gap-2 pt-4">
        <Button onClick={handleSubmit} disabled={isSaveDisabled}>
          {saving ? (
            <>
              <Loader2 className="size-4 animate-spin mr-2" />
              Сохранение...
            </>
          ) : llm ? (
            "Сохранить"
          ) : (
            "Создать"
          )}
        </Button>
        <Button variant="outline" onClick={onCancel} disabled={saving}>
          Отмена
        </Button>
      </div>
    </div>
  );
};

export default LLMForm;
