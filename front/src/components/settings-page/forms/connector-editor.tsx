import React from "react";
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
import { ConnectorForm } from "./provider";
import SchemaFields from "./schema-fields";
import { MANAGED_CONNECTOR_TYPES } from "./types";
import type {
  ConnectorFormMode,
  ConnectorSettings,
  ConnectorType,
  ConnectorTypeMeta,
  JsonSchema,
} from "./types";

export type FormMode = ConnectorFormMode;

export interface ConnectorEditorProps {
  mode: FormMode;
  connectorTypes: ConnectorTypeMeta[];
  selectedType: string;
  connectorName: string;
  settingsValues: Record<string, unknown>;
  settingsSchema: JsonSchema | null;
  isActive: boolean;
  checkConnection: boolean;
  loadingTypes: boolean;
  loadingSchema: boolean;
  saving: boolean;
  submitDisabled: boolean;
  /** When true, hide the type field entirely (single allowed type, create mode). */
  hideTypeSelector?: boolean;
  onTypeChange: (type: string) => void;
  onConnectorNameChange: (name: string) => void;
  onSettingsChange: (settings: Record<string, unknown>) => void;
  onActiveChange: (active: boolean) => void;
  onCheckConnectionChange: (enabled: boolean) => void;
  onSubmit: () => void;
  onCancel: () => void;
  permissionsSection?: React.ReactNode;
}

export const ConnectorEditor: React.FC<ConnectorEditorProps> = ({
  mode,
  connectorTypes,
  selectedType,
  connectorName,
  settingsValues,
  settingsSchema,
  isActive,
  checkConnection,
  loadingTypes,
  loadingSchema,
  saving,
  submitDisabled,
  hideTypeSelector,
  onTypeChange,
  onConnectorNameChange,
  onSettingsChange,
  onActiveChange,
  onCheckConnectionChange,
  onSubmit,
  onCancel,
  permissionsSection,
}) => {
  const isManagedType = MANAGED_CONNECTOR_TYPES.includes(
    selectedType as ConnectorType,
  );

  return (
    <div className="space-y-5">
      {!hideTypeSelector && (
        <div className="space-y-1.5">
          <Label htmlFor="connector-type">
            Тип сервиса <span className="text-destructive">*</span>
          </Label>
          {mode === "create" ? (
            <Select
              value={selectedType}
              onValueChange={onTypeChange}
              disabled={loadingTypes || saving}
            >
              <SelectTrigger id="connector-type" className="w-full">
                {loadingTypes ? (
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" />
                    Загрузка типов...
                  </div>
                ) : (
                  <SelectValue placeholder="Выберите тип сервиса" />
                )}
              </SelectTrigger>
              <SelectContent>
                {connectorTypes.map((item) => (
                  <SelectItem key={item.type} value={item.type}>
                    {item.type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Input id="connector-type" value={selectedType} disabled />
          )}
        </div>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="connector-name">
          Название{" "}
          <span className="text-muted-foreground text-xs font-normal">
            (опционально)
          </span>
        </Label>
        <Input
          id="connector-name"
          placeholder="Мой сервис"
          value={connectorName}
          onChange={(e) => onConnectorNameChange(e.target.value)}
          disabled={saving}
        />
      </div>

      {selectedType && (
        <div className="space-y-2">
          {isManagedType ? (
            <ConnectorForm
              connectorType={selectedType as ConnectorType}
              onConnectorTypeChange={() => {
                // Type is controlled above.
              }}
              showConnectorTypeSelector={false}
              compact
              settings={settingsValues as ConnectorSettings}
              onSettingsChange={(nextSettings) =>
                onSettingsChange(nextSettings as Record<string, unknown>)
              }
            />
          ) : loadingSchema ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Загрузка настроек...
            </div>
          ) : (
            <SchemaFields
              schema={settingsSchema || {}}
              values={settingsValues}
              onChange={onSettingsChange}
              disabled={saving}
              idPrefix="connector-setting"
            />
          )}
        </div>
      )}

      <div className="flex items-center justify-between">
        <Label htmlFor="connector-active">Активен</Label>
        <Switch
          id="connector-active"
          checked={isActive}
          onCheckedChange={onActiveChange}
          disabled={saving}
        />
      </div>

      <div className="flex items-center justify-between">
        <Label htmlFor="connector-check-connection">
          Проверять подключение
        </Label>
        <Switch
          id="connector-check-connection"
          checked={checkConnection}
          onCheckedChange={onCheckConnectionChange}
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

export default ConnectorEditor;
