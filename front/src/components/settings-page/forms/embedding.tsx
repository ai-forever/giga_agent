import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
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
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type {
  ConnectorResponse,
  EmbeddingSettings,
  EmbeddingResponse,
  EmbeddingTypeMeta,
  AvailableEmbeddingModel,
} from "./types";
import { apiClient } from "@/lib/api-client";

interface EmbeddingFormProps {
  embedding?: EmbeddingResponse;
  onSave: (data: EmbeddingFormSubmitData) => void;
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
  const [embeddingTypes, setEmbeddingTypes] = useState<EmbeddingTypeMeta[]>([]);
  const [connectors, setConnectors] = useState<ConnectorResponse[]>([]);

  const [selectedEmbeddingType, setSelectedEmbeddingType] = useState<string>(
    embedding?.type || "",
  );
  const [selectedConnectorId, setSelectedConnectorId] = useState<string>(
    embedding?.connector_id || "",
  );

  const [availableModels, setAvailableModels] = useState<AvailableEmbeddingModel[]>([]);
  const [modelId, setModelId] = useState(embedding?.model_id || "");
  const [embeddingName, setEmbeddingName] = useState(embedding?.name || "");
  const [isActive, setIsActive] = useState(embedding?.is_active ?? true);

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [dimensions, setDimensions] = useState<string>(
    typeof embedding?.settings?.dimensions === "number"
      ? String(embedding.settings.dimensions)
      : "",
  );
  const [chunkSize, setChunkSize] = useState<string>(
    typeof embedding?.settings?.chunk_size === "number"
      ? String(embedding.settings.chunk_size)
      : "",
  );
  const [maxRetries, setMaxRetries] = useState<string>(
    typeof embedding?.settings?.max_retries === "number"
      ? String(embedding.settings.max_retries)
      : "",
  );
  const [requestTimeout, setRequestTimeout] = useState<string>(
    typeof embedding?.settings?.request_timeout === "number"
      ? String(embedding.settings.request_timeout)
      : "",
  );
  const [timeout, setTimeout] = useState<string>(
    typeof embedding?.settings?.timeout === "number"
      ? String(embedding.settings.timeout)
      : "",
  );

  const [loadingEmbeddingTypes, setLoadingEmbeddingTypes] = useState(false);
  const [loadingConnectors, setLoadingConnectors] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);
  const [embeddingTypesLoaded, setEmbeddingTypesLoaded] = useState(false);
  const [connectorsLoaded, setConnectorsLoaded] = useState(false);

  const prevConnectorRef = useRef<string | null>(null);
  const modelsByConnectorRef = useRef<Record<string, AvailableEmbeddingModel[]>>({});

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
      const data = await apiClient.get<EmbeddingTypeMeta[]>("/api/embeddings/types/meta");
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
      const data = await apiClient.get<AvailableEmbeddingModel[]>(
        `/api/embeddings/models/${connectorId}`,
      );
      const models = Array.isArray(data) ? data : [];
      modelsByConnectorRef.current[connectorId] = models;
      if (prevConnectorRef.current === connectorId) {
        setAvailableModels(models);
      }
    } catch {
      // handled globally
      modelsByConnectorRef.current[connectorId] = [];
      if (prevConnectorRef.current === connectorId) {
        setAvailableModels([]);
      }
    } finally {
      setLoadingModels(false);
    }
  }, []);

  useEffect(() => {
    fetchEmbeddingTypes();
    fetchConnectors();
  }, [fetchEmbeddingTypes, fetchConnectors]);

  useEffect(() => {
    if (!selectedConnectorId) {
      setAvailableModels([]);
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

    if (prevConnectorRef.current !== selectedConnectorId) {
      if (selectedConnectorId in modelsByConnectorRef.current) {
        setAvailableModels(modelsByConnectorRef.current[selectedConnectorId]);
      } else {
        setAvailableModels([]);
        fetchModelsForConnector(selectedConnectorId);
      }
      setModelId((prev) =>
        prev && embedding?.connector_id === selectedConnectorId ? prev : "",
      );
    }

    prevConnectorRef.current = selectedConnectorId;
  }, [
    selectedConnectorId,
    filteredConnectors,
    fetchModelsForConnector,
    embedding?.connector_id,
    embeddingTypesLoaded,
    connectorsLoaded,
  ]);

  const handleEmbeddingTypeChange = (type: string) => {
    if (embedding) return;
    setSelectedEmbeddingType(type);
    setSelectedConnectorId("");
    setAvailableModels([]);
    modelsByConnectorRef.current = {};
    setModelId("");
  };

  const parseIntValue = (value: string): number | undefined => {
    if (!value.trim()) return undefined;
    const parsed = parseInt(value, 10);
    return Number.isNaN(parsed) ? undefined : parsed;
  };

  const parseFloatValue = (value: string): number | undefined => {
    if (!value.trim()) return undefined;
    const parsed = parseFloat(value);
    return Number.isNaN(parsed) ? undefined : parsed;
  };

  const handleSubmit = () => {
    if (!selectedEmbeddingType || !selectedConnectorId || !modelId) return;

    const embeddingSettings: EmbeddingSettings = {
      dimensions: parseIntValue(dimensions),
      chunk_size: parseIntValue(chunkSize),
      max_retries: parseIntValue(maxRetries),
      request_timeout: parseFloatValue(requestTimeout),
      timeout: parseFloatValue(timeout),
    };

    const data: EmbeddingFormSubmitData = {
      embedding_type: selectedEmbeddingType,
      connector_id: selectedConnectorId,
      model_id: modelId,
      embedding_name: embeddingName || undefined,
      embedding_settings: embeddingSettings,
      is_active: isActive,
    };

    onSave(data);
  };

  const isSaveDisabled =
    !selectedEmbeddingType ||
    !selectedConnectorId ||
    !modelId ||
    loadingEmbeddingTypes ||
    loadingConnectors ||
    loadingModels;

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
            disabled={loadingEmbeddingTypes}
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
            loadingConnectors || !selectedEmbeddingType || filteredConnectors.length === 0
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
        {selectedEmbeddingType && filteredConnectors.length === 0 && !loadingConnectors && (
          <p className="text-sm text-amber-600">
            Нет активных коннекторов для типа{" "}
            <span className="font-medium">{selectedEmbeddingType}</span>.
          </p>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="embedding-model-id">Название модели</Label>
        {availableModels.length > 0 ? (
          <Select value={modelId} onValueChange={setModelId}>
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
          />
        )}
        {loadingModels && (
          <p className="text-sm text-muted-foreground">Загрузка моделей...</p>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="embedding-name">Отображаемое название (опционально)</Label>
        <Input
          id="embedding-name"
          placeholder="Основной embedding"
          value={embeddingName}
          onChange={(e) => setEmbeddingName(e.target.value)}
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
          <div className="space-y-2">
            <Label htmlFor="embedding-dimensions">Dimensions</Label>
            <Input
              id="embedding-dimensions"
              type="number"
              min={1}
              step={1}
              value={dimensions}
              onChange={(e) => setDimensions(e.target.value)}
              placeholder="1536"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="embedding-chunk-size">Chunk size</Label>
            <Input
              id="embedding-chunk-size"
              type="number"
              min={1}
              step={1}
              value={chunkSize}
              onChange={(e) => setChunkSize(e.target.value)}
              placeholder="256"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="embedding-max-retries">Max retries</Label>
            <Input
              id="embedding-max-retries"
              type="number"
              min={0}
              step={1}
              value={maxRetries}
              onChange={(e) => setMaxRetries(e.target.value)}
              placeholder="2"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="embedding-request-timeout">Request timeout</Label>
            <Input
              id="embedding-request-timeout"
              type="number"
              min={0}
              step="any"
              value={requestTimeout}
              onChange={(e) => setRequestTimeout(e.target.value)}
              placeholder="30"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="embedding-timeout">Timeout</Label>
            <Input
              id="embedding-timeout"
              type="number"
              min={0}
              step="any"
              value={timeout}
              onChange={(e) => setTimeout(e.target.value)}
              placeholder="30"
            />
          </div>
        </CollapsibleContent>
      </Collapsible>

      <div className="flex gap-2 pt-4">
        <Button onClick={handleSubmit} disabled={isSaveDisabled}>
          {embedding ? "Сохранить" : "Создать"}
        </Button>
        <Button variant="outline" onClick={onCancel}>
          Отмена
        </Button>
      </div>
    </div>
  );
};

export default EmbeddingForm;
