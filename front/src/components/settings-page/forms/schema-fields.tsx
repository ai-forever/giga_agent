import React, { Fragment } from "react";
import { Label } from "@/components/ui/label";
import { Input, SecretInput } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { JsonSchema, JsonSchemaProperty } from "./types";
import {
  fieldLabel,
  isFieldRequired,
  isFieldSecret,
  isNullableProperty,
  resolveEnumOptions,
  resolvePropertyType,
} from "./schema-fields-utils";

const UNSET_SELECT_VALUE = "__unset__";
const ENUM_SELECT_PREFIX = "__enum__";

interface SchemaGroup {
  id: string;
  title?: string;
  match: (fieldName: string) => boolean;
  separator?: boolean;
}

interface SchemaFieldsProps {
  schema: JsonSchema;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  disabled?: boolean;
  idPrefix: string;
  emptyState?: React.ReactNode;
  secretDetector?: (fieldName: string) => boolean;
  groups?: SchemaGroup[];
}

function encodeEnumValue(value: string | number | boolean | null): string {
  return `${ENUM_SELECT_PREFIX}${JSON.stringify(value)}`;
}

function decodeEnumValue(value: string): string | number | boolean | null {
  return JSON.parse(value.slice(ENUM_SELECT_PREFIX.length));
}

function formatDefaultValue(
  property: JsonSchemaProperty,
  defaultValue: unknown,
): string {
  const enumOptions = resolveEnumOptions(property);
  const matchedOption = enumOptions.find((option) => option.value === defaultValue);
  if (matchedOption) return matchedOption.label;
  if (typeof defaultValue === "string") return defaultValue;
  if (typeof defaultValue === "number" || typeof defaultValue === "boolean") {
    return String(defaultValue);
  }
  if (defaultValue === null) return "null";
  return JSON.stringify(defaultValue);
}

function renderDefaultHint(property: JsonSchemaProperty): React.ReactNode {
  if (property.default === undefined) return null;
  return (
    <p className="text-xs text-muted-foreground">
      По умолчанию: {formatDefaultValue(property, property.default)}
    </p>
  );
}

const SchemaFields: React.FC<SchemaFieldsProps> = ({
  schema,
  values,
  onChange,
  disabled,
  idPrefix,
  emptyState,
  secretDetector = isFieldSecret,
  groups,
}) => {
  const entries = Object.entries(schema.properties || {});

  if (entries.length === 0) {
    return (
      <>
        {emptyState || (
          <p className="text-sm text-muted-foreground">
            Для этого типа нет дополнительных настроек.
          </p>
        )}
      </>
    );
  }

  const setFieldValue = (name: string, value: unknown) => {
    onChange({ ...values, [name]: value });
  };

  const renderField = ([name, property]: [string, JsonSchemaProperty]) => {
    const required = isFieldRequired(name, schema);
    const nullable = isNullableProperty(property);
    const rawValue = values[name];
    const enumOptions = resolveEnumOptions(property);
    const hasEnum = enumOptions.length > 0;
    const label = fieldLabel(name, property);

    if (hasEnum) {
      const selectValue =
        rawValue === undefined
          ? nullable
            ? UNSET_SELECT_VALUE
            : undefined
          : encodeEnumValue(rawValue as string | number | boolean | null);

      return (
        <div key={name} className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-${name}`}>
            {label}
            {required && <span className="text-destructive ml-1">*</span>}
            {!required && nullable && (
              <span className="text-muted-foreground ml-1 text-xs font-normal">
                (опционально)
              </span>
            )}
          </Label>
          <Select
            value={selectValue}
            onValueChange={(next) => {
              if (next === UNSET_SELECT_VALUE) {
                setFieldValue(name, undefined);
                return;
              }
              setFieldValue(name, decodeEnumValue(next));
            }}
            disabled={disabled}
          >
            <SelectTrigger id={`${idPrefix}-${name}`} className="w-full">
              <SelectValue placeholder="Выберите значение" />
            </SelectTrigger>
            <SelectContent>
              {nullable && (
                <SelectItem value={UNSET_SELECT_VALUE}>Не задано</SelectItem>
              )}
              {enumOptions.map((option) => (
                <SelectItem
                  key={encodeEnumValue(option.value)}
                  value={encodeEnumValue(option.value)}
                >
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {renderDefaultHint(property)}
          {property.description && (
            <p className="text-xs text-muted-foreground">{property.description}</p>
          )}
        </div>
      );
    }

    const propertyType = resolvePropertyType(property);

    if (propertyType === "boolean") {
      return (
        <div key={name} className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor={`${idPrefix}-${name}`}>
              {label}
              {required && <span className="text-destructive ml-1">*</span>}
            </Label>
            <Switch
              id={`${idPrefix}-${name}`}
              checked={Boolean(rawValue)}
              onCheckedChange={(checked) => setFieldValue(name, checked)}
              disabled={disabled}
            />
          </div>
          {renderDefaultHint(property)}
          {property.description && (
            <p className="text-xs text-muted-foreground">{property.description}</p>
          )}
        </div>
      );
    }

    if (propertyType === "number" || propertyType === "integer") {
      const value = typeof rawValue === "number" ? String(rawValue) : "";
      return (
        <div key={name} className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-${name}`}>
            {label}
            {required && <span className="text-destructive ml-1">*</span>}
            {!required && nullable && (
              <span className="text-muted-foreground ml-1 text-xs font-normal">
                (опционально)
              </span>
            )}
          </Label>
          <Input
            id={`${idPrefix}-${name}`}
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
            <p className="text-xs text-muted-foreground">{property.description}</p>
          )}
        </div>
      );
    }

    const InputComponent = secretDetector(name) ? SecretInput : Input;
    const value = typeof rawValue === "string" ? rawValue : "";

    return (
      <div key={name} className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-${name}`}>
          {label}
          {required && <span className="text-destructive ml-1">*</span>}
          {!required && nullable && (
            <span className="text-muted-foreground ml-1 text-xs font-normal">
              (опционально)
            </span>
          )}
        </Label>
        <InputComponent
          id={`${idPrefix}-${name}`}
          value={value}
          placeholder={
            property.default !== undefined
              ? String(property.default)
              : property.description || ""
          }
          onChange={(e) => setFieldValue(name, e.target.value || undefined)}
          disabled={disabled}
        />
        {property.description && (
          <p className="text-xs text-muted-foreground">{property.description}</p>
        )}
      </div>
    );
  };

  if (!groups || groups.length === 0) {
    return <div className="space-y-4">{entries.map(renderField)}</div>;
  }

  const assigned = new Set<string>();
  const groupedSections = groups
    .map((group) => {
      const groupEntries = entries.filter(([name]) => {
        if (assigned.has(name)) return false;
        if (!group.match(name)) return false;
        assigned.add(name);
        return true;
      });
      return { group, groupEntries };
    })
    .filter(({ groupEntries }) => groupEntries.length > 0);

  const remainingEntries = entries.filter(([name]) => !assigned.has(name));

  return (
    <div className="space-y-4">
      {groupedSections.map(({ group, groupEntries }) => (
        <Fragment key={group.id}>
          {group.title && group.separator && (
            <div className="flex items-center gap-2 pt-2">
              <div className="h-px flex-1 bg-border" />
              <span className="text-xs text-muted-foreground">{group.title}</span>
              <div className="h-px flex-1 bg-border" />
            </div>
          )}
          {group.title && !group.separator && (
            <p className="text-xs text-muted-foreground">{group.title}</p>
          )}
          {groupEntries.map(renderField)}
        </Fragment>
      ))}
      {remainingEntries.map(renderField)}
    </div>
  );
};

export default SchemaFields;
