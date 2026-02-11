import React, { useState, useEffect, useRef, useCallback } from "react";
import { ChevronDown, Plus, Loader2 } from "lucide-react";
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
import { ProviderForm } from "./provider";
import type {
  ProviderType,
  ProviderSettings,
  ProviderResponse,
  AvailableModel,
  LLMSettings,
  LLMResponse,
} from "./types";
import { apiClient } from "@/lib/api-client";

interface LLMFormProps {
  llm?: LLMResponse;
  onSave: (data: LLMFormSubmitData) => void;
  onCancel: () => void;
}

export interface LLMFormSubmitData {
  // Existing provider or new one
  provider_id?: string;
  // New provider data
  provider_type?: string;
  provider_name?: string;
  provider_settings?: ProviderSettings;
  // LLM data
  model_id: string;
  llm_name?: string;
  llm_settings: LLMSettings;
  is_active: boolean;
}

const CREATE_NEW_PROVIDER = "__create_new__";

export const LLMForm: React.FC<LLMFormProps> = ({
  llm,
  onSave,
  onCancel,
}) => {
  // Provider state
  const [providers, setProviders] = useState<ProviderResponse[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState<string>(
    llm?.provider_id || CREATE_NEW_PROVIDER
  );
  const [showNewProviderForm, setShowNewProviderForm] = useState(!selectedProviderId);
  const [newProviderType, setNewProviderType] = useState<ProviderType>("openai");
  const [newProviderSettings, setNewProviderSettings] = useState<ProviderSettings>({});
  const [newProviderName, setNewProviderName] = useState("");

  // Model state
  const [availableModels, setAvailableModels] = useState<AvailableModel[]>([]);
  const [modelId, setModelId] = useState(llm?.model_id || "");
  const [llmName, setLlmName] = useState(llm?.name || "");
  const [isActive, setIsActive] = useState(llm?.is_active ?? true);

  // Settings state
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [temperature, setTemperature] = useState<number>(
    llm?.settings?.temperature ?? 0.7
  );
  const [tempInput, setTempInput] = useState<string>(
    String(llm?.settings?.temperature ?? 0.7)
  );

  // Loading state
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);

  // Track previous provider for model fetching
  const prevProviderRef = useRef<string | null>(null);
  const modelsFetchedRef = useRef<Set<string>>(new Set());

  // Fetch providers on mount
  useEffect(() => {
    fetchProviders();
  }, []);

  // Handle provider selection change
  useEffect(() => {
    if (selectedProviderId === CREATE_NEW_PROVIDER) {
      setShowNewProviderForm(true);
      setAvailableModels([]);
    } else {
      setShowNewProviderForm(false);
      // Only fetch models if provider changed and not already fetched
      if (
        selectedProviderId &&
        prevProviderRef.current !== selectedProviderId &&
        !modelsFetchedRef.current.has(selectedProviderId)
      ) {
        fetchModelsForProvider(selectedProviderId);
        modelsFetchedRef.current.add(selectedProviderId);
      }
      prevProviderRef.current = selectedProviderId;
    }
  }, [selectedProviderId]);

  // Initialize from existing LLM's provider
  useEffect(() => {
    if (llm?.provider_id && providers.length > 0) {
      const existingProvider = providers.find(p => p.id === llm.provider_id);
      if (existingProvider) {
        setSelectedProviderId(existingProvider.id);
        setNewProviderType(existingProvider.type as ProviderType);
        setNewProviderSettings(existingProvider.settings);
        setNewProviderName(existingProvider.name || "");
      }
    }
  }, [llm?.provider_id, providers]);

  const fetchProviders = useCallback(async () => {
    setLoadingProviders(true);
    try {
      const data = await apiClient.get<ProviderResponse[]>("/api/llms/providers");
      setProviders(data);
    } catch {
      // Ошибка уже обработана глобально
    } finally {
      setLoadingProviders(false);
    }
  }, []);

  const fetchModelsForProvider = useCallback(async (providerId: string) => {
    setLoadingModels(true);
    try {
      const data = await apiClient.get<AvailableModel[]>(`/api/llms/providers/${providerId}/models`);
      setAvailableModels(data);
    } catch {
      // Ошибка уже обработана глобально
    } finally {
      setLoadingModels(false);
    }
  }, []);

  const fetchModelsForNewProvider = useCallback(async () => {
    setLoadingModels(true);
    try {
      const data = await apiClient.post<AvailableModel[]>("/api/llms/providers/models/fetch", {
        provider_type: newProviderType,
        settings: newProviderSettings,
      });
      setAvailableModels(data);
    } catch {
      // Ошибка уже обработана глобально
    } finally {
      setLoadingModels(false);
    }
  }, [newProviderType, newProviderSettings]);

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
    const data: LLMFormSubmitData = {
      model_id: modelId,
      llm_name: llmName || undefined,
      llm_settings: {
        temperature,
      },
      is_active: isActive,
    };

    if (selectedProviderId === CREATE_NEW_PROVIDER) {
      data.provider_type = newProviderType;
      data.provider_name = newProviderName || undefined;
      data.provider_settings = newProviderSettings;
    } else {
      data.provider_id = selectedProviderId;
    }

    onSave(data);
  };

  return (
    <div className="space-y-6">
      {/* Provider selection */}
      <div className="space-y-2">
        <Label htmlFor="provider-select">Провайдер</Label>
        <Select
          value={selectedProviderId}
          onValueChange={setSelectedProviderId}
          disabled={loadingProviders}
        >
          <SelectTrigger id="provider-select" className="w-full">
            {loadingProviders ? (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Загрузка провайдеров...
              </div>
            ) : (
              <SelectValue placeholder="Выберите провайдера" />
            )}
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={CREATE_NEW_PROVIDER}>
              <div className="flex items-center gap-2">
                <Plus className="size-4" />
                Создать новый
              </div>
            </SelectItem>
            {providers.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name || p.type}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* New provider form */}
      {showNewProviderForm && (
        <div className="space-y-4">
          <ProviderForm
            providerType={newProviderType}
            onProviderTypeChange={setNewProviderType}
            settings={newProviderSettings}
            onSettingsChange={setNewProviderSettings}
            providerName={newProviderName}
            onProviderNameChange={setNewProviderName}
          />
          <Button
            variant="outline"
            size="sm"
            onClick={fetchModelsForNewProvider}
            disabled={loadingModels}
          >
            {loadingModels ? (
              <>
                <Loader2 className="size-4 animate-spin mr-2" />
                Загрузка...
              </>
            ) : (
              "Загрузить модели"
            )}
          </Button>
        </div>
      )}

      {/* Model name */}
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

      {/* LLM display name */}
      <div className="space-y-2">
        <Label htmlFor="llm-name">Отображаемое название (опционально)</Label>
        <Input
          id="llm-name"
          placeholder="Мой GPT-4"
          value={llmName}
          onChange={(e) => setLlmName(e.target.value)}
        />
      </div>

      {/* Advanced settings */}
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
          {/* Temperature */}
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

      {/* Action buttons */}
      <div className="flex gap-2 pt-4">
        <Button onClick={handleSubmit} disabled={!modelId}>
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
