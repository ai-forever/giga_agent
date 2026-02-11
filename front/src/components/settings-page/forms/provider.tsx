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
import type { ProviderType, ProviderSettings, GigaChatApiType, GigaChatScope } from "./types";

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

interface ProviderFormProps {
  providerType: ProviderType;
  onProviderTypeChange: (type: ProviderType) => void;
  settings: ProviderSettings;
  onSettingsChange: (settings: ProviderSettings) => void;
  providerName?: string;
  onProviderNameChange?: (name: string) => void;
}

const PROVIDER_TYPES: { id: ProviderType; label: string }[] = [
  { id: "openai", label: "OpenAI Compatible" },
  { id: "gigachat", label: "GigaChat" },
];

export const ProviderForm: React.FC<ProviderFormProps> = ({
  providerType,
  onProviderTypeChange,
  settings,
  onSettingsChange,
  providerName,
  onProviderNameChange,
}) => {
  const handleProviderTypeChange = (type: ProviderType) => {
    onProviderTypeChange(type);
  };

  const handleSettingChange = (key: keyof ProviderSettings, value: string) => {
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
          placeholder="https://api.openai.com/v1"
          value={settings.base_url || ""}
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

  const gigachatApiType = (settings.gigachat_api_type || "prod") as GigaChatApiType;
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
              onChange={(e) => handleSettingChange("gigachat_credentials", e.target.value)}
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
              onChange={(e) => handleSettingChange("gigachat_username", e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="gigachat_password">Password</Label>
            <SecretInput
              id="gigachat_password"
              placeholder="Пароль"
              value={settings.gigachat_password || ""}
              onChange={(e) => handleSettingChange("gigachat_password", e.target.value)}
            />
          </div>
        </>
      )}
    </div>
  );

  return (
    <div className="space-y-4 p-4 border border-border rounded-lg bg-muted/30">
      <div className="space-y-2">
        <Label>Тип провайдера</Label>
        <div className="flex gap-2">
          {PROVIDER_TYPES.map((type) => (
            <Badge
              key={type.id}
              variant={providerType === type.id ? "default" : "outline"}
              className="cursor-pointer px-3 py-1.5"
              onClick={() => handleProviderTypeChange(type.id)}
            >
              {type.label}
            </Badge>
          ))}
        </div>
      </div>

      {onProviderNameChange && (
        <div className="space-y-2">
          <Label htmlFor="provider_name">Название провайдера</Label>
          <Input
            id="provider_name"
            placeholder="Мой провайдер"
            value={providerName || ""}
            onChange={(e) => onProviderNameChange(e.target.value)}
          />
        </div>
      )}

      {providerType === "openai" && renderOpenAIFields()}
      {providerType === "gigachat" && renderGigaChatFields()}
    </div>
  );
};

export default ProviderForm;
