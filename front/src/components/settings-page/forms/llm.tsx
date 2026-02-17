import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
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
} from "./types";
import { apiClient } from "@/lib/api-client";

interface LLMFormProps {
  llm?: LLMResponse;
  onSave: (data: LLMFormSubmitData) => void;
  onCancel: () => void;
}

export interface LLMFormSubmitData {
  connector_id: string;
  llm_type: string;
  model_id: string;
  llm_name?: string;
  llm_settings: LLMSettings;
  is_active: boolean;
}

export const LLMForm: React.FC<LLMFormProps> = ({
  llm,
  onSave,
  onCancel,
}) => {
  const [llmTypes, setLlmTypes] = useState<LLMTypeMeta[]>([]);
  const [connectors, setConnectors] = useState<ConnectorResponse[]>([]);

  const [selectedLLMType, setSelectedLLMType] = useState<string>(llm?.type || "");
  const [selectedConnectorId, setSelectedConnectorId] = useState<string>(
    llm?.connector_id || "",
  );

  const [availableModels, setAvailableModels] = useState<AvailableModel[]>([]);
  const [modelId, setModelId] = useState(llm?.model_id || "");
  const [llmName, setLlmName] = useState(llm?.name || "");
  const [isActive, setIsActive] = useState(llm?.is_active ?? true);

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [temperature, setTemperature] = useState<number>(
    llm?.settings?.temperature ?? 0.7,
  );
  const [tempInput, setTempInput] = useState<string>(
    String(llm?.settings?.temperature ?? 0.7),
  );

  const [loadingLLMTypes, setLoadingLLMTypes] = useState(false);
  const [loadingConnectors, setLoadingConnectors] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);
  const [llmTypesLoaded, setLlmTypesLoaded] = useState(false);
  const [connectorsLoaded, setConnectorsLoaded] = useState(false);

  const prevConnectorRef = useRef<string | null>(null);
  const modelsFetchedRef = useRef<Set<string>>(new Set());

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

  const fetchLLMTypes = useCallback(async () => {
    setLoadingLLMTypes(true);
    try {
      const data = await apiClient.get<LLMTypeMeta[]>("/api/llms/types/meta");
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
        "/api/connectors?only_active=true",
      );
      setConnectors(data);
    } catch {
      // handled globally
    } finally {
      setLoadingConnectors(false);
      setConnectorsLoaded(true);
    }
  }, []);

  const fetchModelsForConnector = useCallback(async (connectorId: string) => {
    setLoadingModels(true);
    try {
      const data = await apiClient.get<AvailableModel[]>(`/api/llms/models/${connectorId}`);
      setAvailableModels(data);
    } catch {
      // handled globally
    } finally {
      setLoadingModels(false);
    }
  }, []);

  useEffect(() => {
    fetchLLMTypes();
    fetchConnectors();
  }, [fetchLLMTypes, fetchConnectors]);

  useEffect(() => {
    if (!selectedConnectorId) {
      setAvailableModels([]);
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

    if (
      prevConnectorRef.current !== selectedConnectorId &&
      !modelsFetchedRef.current.has(selectedConnectorId)
    ) {
      fetchModelsForConnector(selectedConnectorId);
      modelsFetchedRef.current.add(selectedConnectorId);
      setModelId((prev) => (prev && llm?.connector_id === selectedConnectorId ? prev : ""));
    }

    prevConnectorRef.current = selectedConnectorId;
  }, [
    selectedConnectorId,
    filteredConnectors,
    fetchModelsForConnector,
    llm?.connector_id,
    llmTypesLoaded,
    connectorsLoaded,
  ]);

  const handleLLMTypeChange = (type: string) => {
    if (llm) return;
    setSelectedLLMType(type);
    setSelectedConnectorId("");
    setAvailableModels([]);
    setModelId("");
  };

  const handleTemperatureSliderChange = (values: number[]) => {
    const value = values[0];
    setTemperature(value);
    setTempInput(value.toFixed(2));
  };

  const handleTemperatureInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
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
      llm_settings: {
        temperature,
      },
      is_active: isActive,
    };

    onSave(data);
  };

  const isSaveDisabled =
    !selectedLLMType ||
    !selectedConnectorId ||
    !modelId ||
    loadingLLMTypes ||
    loadingConnectors ||
    loadingModels;

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
            disabled={loadingLLMTypes}
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
        <Select
          value={selectedConnectorId}
          onValueChange={setSelectedConnectorId}
          disabled={loadingConnectors || !selectedLLMType || filteredConnectors.length === 0}
        >
          <SelectTrigger id="connector-select" className="w-full">
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
        {selectedLLMType && filteredConnectors.length === 0 && !loadingConnectors && (
          <p className="text-sm text-amber-600">
            Нет активных коннекторов для типа <span className="font-medium">{selectedLLMType}</span>.
          </p>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="model-id">Название модели</Label>
        {availableModels.length > 0 ? (
          <Select value={modelId} onValueChange={setModelId}>
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
        />
      </div>

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
              />
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      <div className="flex gap-2 pt-4">
        <Button onClick={handleSubmit} disabled={isSaveDisabled}>
          {llm ? "Сохранить" : "Создать"}
        </Button>
        <Button variant="outline" onClick={onCancel}>
          Отмена
        </Button>
      </div>
    </div>
  );
};

export default LLMForm;
