import React from "react";
import { Label } from "@/components/ui/label";
import { Input, SecretInput } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  ConnectorType,
  ConnectorSettings,
  GigaChatApiType,
  GigaChatScope,
} from "./types";

const OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1";

const GIGACHAT_API_TYPES: { id: GigaChatApiType; label: string }[] = [
  { id: "prod", label: "GigaChat Prod" },
  { id: "preview", label: "GigaChat Preview" },
  { id: "dev", label: "GigaChat Dev Server" },
];

const GIGACHAT_SCOPES: { id: GigaChatScope; label: string }[] = [
  { id: "GIGACHAT_API_PERS", label: "GIGACHAT_API_PERS" },
  { id: "GIGACHAT_API_B2B", label: "GIGACHAT_API_B2B" },
  { id: "GIGACHAT_API_CORP", label: "GIGACHAT_API_CORP" },
];

interface ConnectorFormProps {
  connectorType: ConnectorType;
  onConnectorTypeChange: (type: ConnectorType) => void;
  settings: ConnectorSettings;
  onSettingsChange: (settings: ConnectorSettings) => void;
  connectorName?: string;
  onConnectorNameChange?: (name: string) => void;
  showConnectorTypeSelector?: boolean;
  compact?: boolean;
}

const CONNECTOR_TYPES: { id: ConnectorType; label: string }[] = [
  { id: "openai", label: "OpenAI Compatible" },
  { id: "gigachat", label: "GigaChat" },
];

export const ConnectorForm: React.FC<ConnectorFormProps> = ({
  connectorType,
  onConnectorTypeChange,
  settings,
  onSettingsChange,
  connectorName,
  onConnectorNameChange,
  showConnectorTypeSelector = true,
  compact = false,
}) => {
  const handleConnectorTypeChange = (type: ConnectorType) => {
    onConnectorTypeChange(type);
  };

  const handleSettingChange = (key: keyof ConnectorSettings, value: string) => {
    onSettingsChange({
      ...settings,
      [key]: value || undefined,
    });
  };

  const renderOpenAIFields = () => (
    <div className="space-y-4 mt-4">
      <div className="space-y-2">
        <Label htmlFor="base_url">Base URL</Label>
        <Input
          id="base_url"
          placeholder={OPENAI_DEFAULT_BASE_URL}
          value={settings.base_url || OPENAI_DEFAULT_BASE_URL}
          onChange={(e) => handleSettingChange("base_url", e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="api_key">API Token</Label>
        <SecretInput
          id="api_key"
          placeholder="sk-..."
          value={settings.api_key || ""}
          onChange={(e) => handleSettingChange("api_key", e.target.value)}
        />
      </div>
    </div>
  );

  const gigachatApiType = (settings.gigachat_api_type ||
    "prod") as GigaChatApiType;
  const isGigaChatDev = gigachatApiType === "dev";

  const renderGigaChatFields = () => (
    <div className="space-y-4 mt-4">
      <div className="space-y-2">
        <Label htmlFor="gigachat_api_type">Тип API</Label>
        <Select
          value={gigachatApiType}
          onValueChange={(v) => {
            onSettingsChange({ gigachat_api_type: v as GigaChatApiType });
          }}
        >
          <SelectTrigger id="gigachat_api_type" className="w-full">
            <SelectValue placeholder="Выберите тип API" />
          </SelectTrigger>
          <SelectContent>
            {GIGACHAT_API_TYPES.map((t) => (
              <SelectItem key={t.id} value={t.id}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {!isGigaChatDev && (
        <>
          <div className="space-y-2">
            <Label htmlFor="gigachat_credentials">Credentials</Label>
            <SecretInput
              id="gigachat_credentials"
              placeholder="Введите токен GigaChat"
              value={settings.gigachat_credentials || ""}
              onChange={(e) =>
                handleSettingChange("gigachat_credentials", e.target.value)
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="gigachat_scope">Scope</Label>
            <Select
              value={settings.gigachat_scope || "GIGACHAT_API_PERS"}
              onValueChange={(v) => handleSettingChange("gigachat_scope", v)}
            >
              <SelectTrigger id="gigachat_scope" className="w-full">
                <SelectValue placeholder="Выберите scope" />
              </SelectTrigger>
              <SelectContent>
                {GIGACHAT_SCOPES.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      )}

      {isGigaChatDev && (
        <>
          <div className="space-y-2">
            <Label htmlFor="gigachat_base_url">Base URL</Label>
            <Input
              id="gigachat_base_url"
              placeholder="GigaChat Base URL"
              value={settings.base_url || ""}
              onChange={(e) => handleSettingChange("base_url", e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="gigachat_username">Username</Label>
            <Input
              id="gigachat_username"
              placeholder="Логин"
              value={settings.gigachat_username || ""}
              onChange={(e) =>
                handleSettingChange("gigachat_username", e.target.value)
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="gigachat_password">Password</Label>
            <SecretInput
              id="gigachat_password"
              placeholder="Пароль"
              value={settings.gigachat_password || ""}
              onChange={(e) =>
                handleSettingChange("gigachat_password", e.target.value)
              }
            />
          </div>
        </>
      )}
    </div>
  );

  return (
    <div
      className={
        compact
          ? "space-y-4"
          : "space-y-4 p-4 border border-border rounded-lg bg-muted/20"
      }
    >
      {showConnectorTypeSelector && (
        <div className="space-y-2">
          <Label>Тип коннектора</Label>
          <div className="flex gap-2">
            {CONNECTOR_TYPES.map((type) => (
              <Badge
                key={type.id}
                variant={connectorType === type.id ? "default" : "outline"}
                className="cursor-pointer px-3 py-1.5"
                onClick={() => handleConnectorTypeChange(type.id)}
              >
                {type.label}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {onConnectorNameChange && (
        <div className="space-y-2">
          <Label htmlFor="connector_name">Название коннектора</Label>
          <Input
            id="connector_name"
            placeholder="Мой коннектор"
            value={connectorName || ""}
            onChange={(e) => onConnectorNameChange(e.target.value)}
          />
        </div>
      )}

      {connectorType === "openai" && renderOpenAIFields()}
      {connectorType === "gigachat" && renderGigaChatFields()}
    </div>
  );
};

export default ConnectorForm;
