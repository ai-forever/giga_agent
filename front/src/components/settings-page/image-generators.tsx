import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
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
import type {
  ImageGeneratorResponse,
  ImageGeneratorTypeMeta,
  ProviderResponse,
} from "./forms/types";

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
          const value =
            typeof rawValue === "number" ? String(rawValue) : "";
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
              <p className="text-xs text-muted-foreground">{property.description}</p>
            )}
          </div>
        );
      })}
    </div>
  );
};

export const ImageGeneratorsSettings: React.FC = () => {
  const [generatorTypes, setGeneratorTypes] = useState<ImageGeneratorTypeMeta[]>([]);
  const [providers, setProviders] = useState<ProviderResponse[]>([]);
  const [generators, setGenerators] = useState<ImageGeneratorResponse[]>([]);

  const [selectedType, setSelectedType] = useState("");
  const [generatorName, setGeneratorName] = useState("");
  const [settingsSchema, setSettingsSchema] = useState<JsonSchema | null>(null);
  const [settingsValues, setSettingsValues] = useState<Record<string, unknown>>({});
  const [selectedProviderId, setSelectedProviderId] = useState("");
  const [isActive, setIsActive] = useState(true);

  const [loadingTypes, setLoadingTypes] = useState(false);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [loadingGenerators, setLoadingGenerators] = useState(false);
  const [saving, setSaving] = useState(false);

  const fetchGeneratorTypes = useCallback(async () => {
    setLoadingTypes(true);
    try {
      const data = await apiClient.get<ImageGeneratorTypeMeta[]>(
        "/api/generators/image/types/meta",
      );
      setGeneratorTypes(data);
    } catch {
      // Handled globally
    } finally {
      setLoadingTypes(false);
    }
  }, []);

  const fetchProviders = useCallback(async () => {
    setLoadingProviders(true);
    try {
      const data = await apiClient.get<ProviderResponse[]>(
        "/api/llms/providers?only_active=true",
      );
      setProviders(data);
    } catch {
      // Handled globally
    } finally {
      setLoadingProviders(false);
    }
  }, []);

  const fetchGenerators = useCallback(async () => {
    setLoadingGenerators(true);
    try {
      const data = await apiClient.get<ImageGeneratorResponse[]>(
        "/api/generators/image",
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
    fetchProviders();
    fetchGenerators();
  }, [fetchGeneratorTypes, fetchProviders, fetchGenerators]);

  useEffect(() => {
    if (!selectedType) {
      setSettingsSchema(null);
      setSettingsValues({});
      return;
    }

    let cancelled = false;
    setLoadingSchema(true);
    setSettingsSchema(null);
    setSettingsValues({});

    const run = async () => {
      try {
        const schema = await apiClient.get<JsonSchema>(
          `/api/generators/image/types/${selectedType}/settings-schema`,
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

  const requiresLlmProvider = selectedTypeMeta?.requires_llm_provider ?? false;
  const supportedProviderTypes = useMemo(
    () =>
      (selectedTypeMeta?.supported_llm_provider_types || []).map((type) =>
        type.toLowerCase(),
      ),
    [selectedTypeMeta],
  );

  const filteredProviders = useMemo(
    () =>
      providers.filter((provider) =>
        supportedProviderTypes.includes((provider.type || "").toLowerCase()),
      ),
    [providers, supportedProviderTypes],
  );

  useEffect(() => {
    if (!selectedProviderId) return;
    const exists = filteredProviders.some((provider) => provider.id === selectedProviderId);
    if (!exists) {
      setSelectedProviderId("");
    }
  }, [filteredProviders, selectedProviderId]);

  const providersMap = useMemo(
    () => new Map(providers.map((provider) => [provider.id, provider])),
    [providers],
  );

  const resetForm = () => {
    setSelectedType("");
    setGeneratorName("");
    setSettingsSchema(null);
    setSettingsValues({});
    setSelectedProviderId("");
    setIsActive(true);
  };

  const handleCreate = async () => {
    if (!selectedType) return;
    if (requiresLlmProvider && (!selectedProviderId || filteredProviders.length === 0)) {
      return;
    }

    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        type: selectedType,
        settings: compactObject(settingsValues),
        is_active: isActive,
      };

      const trimmedName = generatorName.trim();
      if (trimmedName) {
        payload.name = trimmedName;
      }

      if (requiresLlmProvider) {
        payload.llm_provider_id = selectedProviderId;
      }

      await apiClient.post<ImageGeneratorResponse>("/api/generators/image", payload);
      toast.success("Image generator создан");
      resetForm();
      fetchGenerators();
    } catch {
      // Handled globally
    } finally {
      setSaving(false);
    }
  };

  const isCreateDisabled =
    saving ||
    loadingSchema ||
    !selectedType ||
    (requiresLlmProvider && (!selectedProviderId || filteredProviders.length === 0));

  return (
    <div className="space-y-6">
      <div>
        <h3 className="font-medium">Image Generators</h3>
        <p className="text-sm text-muted-foreground mt-1">
          Создание генераторов изображений с привязкой к LLM provider
        </p>
      </div>

      <div className="border border-border rounded-lg p-5 bg-muted/30 space-y-5">
        <h4 className="font-medium">Новый image generator</h4>

        <div className="space-y-1.5">
          <Label htmlFor="image-generator-type">
            Тип генератора <span className="text-destructive">*</span>
          </Label>
          <Select value={selectedType} onValueChange={setSelectedType} disabled={loadingTypes || saving}>
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
            onChange={(e) => setGeneratorName(e.target.value)}
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
                onChange={setSettingsValues}
                disabled={saving}
              />
            )}
          </div>
        )}

        {selectedType && requiresLlmProvider && (
          <div className="space-y-1.5">
            <Label htmlFor="image-generator-provider">
              LLM Provider <span className="text-destructive">*</span>
            </Label>
            <Select
              value={selectedProviderId}
              onValueChange={setSelectedProviderId}
              disabled={loadingProviders || saving || filteredProviders.length === 0}
            >
              <SelectTrigger id="image-generator-provider" className="w-full">
                {loadingProviders ? (
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" />
                    Загрузка провайдеров...
                  </div>
                ) : (
                  <SelectValue placeholder="Выберите LLM provider" />
                )}
              </SelectTrigger>
              <SelectContent>
                {filteredProviders.map((provider) => (
                  <SelectItem key={provider.id} value={provider.id}>
                    {provider.name || provider.type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {filteredProviders.length === 0 && !loadingProviders && (
              <p className="text-sm text-amber-600">
                Нет активных LLM provider для типа{" "}
                <span className="font-medium">{selectedType}</span>.
              </p>
            )}
          </div>
        )}

        {selectedType && !requiresLlmProvider && (
          <p className="text-sm text-muted-foreground">
            Для выбранного типа генератора LLM provider не требуется.
          </p>
        )}

        <div className="flex items-center justify-between">
          <Label htmlFor="image-generator-active">Активен</Label>
          <Switch
            id="image-generator-active"
            checked={isActive}
            onCheckedChange={setIsActive}
            disabled={saving}
          />
        </div>

        <div className="flex gap-2 pt-2">
          <Button onClick={handleCreate} disabled={isCreateDisabled}>
            {saving ? (
              <>
                <Loader2 className="size-4 animate-spin mr-2" />
                Сохранение...
              </>
            ) : (
              "Создать"
            )}
          </Button>
          <Button variant="outline" onClick={resetForm} disabled={saving}>
            Сбросить
          </Button>
        </div>
      </div>

      <div className="space-y-4">
        <h4 className="font-medium">Созданные генераторы</h4>

        {loadingGenerators && (
          <p className="text-center text-muted-foreground py-6">Загрузка...</p>
        )}

        {!loadingGenerators && generators.length === 0 && (
          <p className="text-center text-muted-foreground py-6">
            Нет добавленных image generators
          </p>
        )}

        {!loadingGenerators &&
          generators.map((generator) => {
            const provider = generator.llm_provider_id
              ? providersMap.get(generator.llm_provider_id)
              : undefined;

            return (
              <div
                key={generator.id}
                className="flex items-center justify-between p-4 border border-border rounded-lg bg-card"
              >
                <div className="flex flex-col gap-1">
                  <span className="font-medium">
                    {generator.name || generator.type}
                  </span>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span>Тип: {generator.type}</span>
                    {generator.llm_provider_id && (
                      <span>
                        Provider:{" "}
                        {provider?.name || provider?.type || generator.llm_provider_id}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{generator.type}</Badge>
                  <Badge variant={generator.is_active ? "default" : "secondary"}>
                    {generator.is_active ? "Активен" : "Неактивен"}
                  </Badge>
                </div>
              </div>
            );
          })}
      </div>
    </div>
  );
};

export default ImageGeneratorsSettings;
