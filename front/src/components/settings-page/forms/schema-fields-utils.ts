import type { JsonSchema, JsonSchemaProperty } from "./types";

export type SupportedPropertyType = "string" | "number" | "integer" | "boolean";

export type EnumOption = {
  value: string | number | boolean | null;
  label: string;
};

function titleCaseFromSnakeCase(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function fieldLabel(name: string, property: JsonSchemaProperty): string {
  if (property.title) return property.title;
  return titleCaseFromSnakeCase(name);
}

export function isFieldRequired(name: string, schema: JsonSchema): boolean {
  return schema.required?.includes(name) ?? false;
}

export function isFieldSecret(name: string): boolean {
  const lower = name.toLowerCase();
  return (
    lower.includes("key") ||
    lower.includes("secret") ||
    lower.includes("password") ||
    lower.includes("token") ||
    lower.includes("credential")
  );
}

export function resolvePropertyType(
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

export function isNullableProperty(property: JsonSchemaProperty): boolean {
  if ((property.anyOf || []).some((item) => item.type === "null")) {
    return true;
  }
  if ((property.enum || []).some((item) => item === null)) {
    return true;
  }
  return (property.oneOf || []).some((item) => item.type === "null");
}

function toEnumOption(value: unknown, index: number): EnumOption | null {
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean" ||
    value === null
  ) {
    return {
      value,
      label: value === null ? "null" : String(value),
    };
  }

  return {
    value: String(value),
    label: `Option ${index + 1}`,
  };
}

export function resolveEnumOptions(property: JsonSchemaProperty): EnumOption[] {
  const options: EnumOption[] = [];
  const seen = new Set<string>();

  const pushOption = (option: EnumOption | null) => {
    if (!option) return;
    const key = JSON.stringify(option.value);
    if (seen.has(key)) return;
    seen.add(key);
    options.push(option);
  };

  for (const [index, value] of (property.enum || []).entries()) {
    pushOption(toEnumOption(value, index));
  }

  for (const item of property.oneOf || []) {
    if (!("const" in item)) continue;
    const option = toEnumOption(item.const, options.length);
    if (!option) continue;
    pushOption({
      ...option,
      label: item.title || option.label,
    });
  }

  for (const item of property.anyOf || []) {
    for (const value of item.enum || []) {
      pushOption(toEnumOption(value, options.length));
    }
    if (!("const" in item)) continue;
    const option = toEnumOption(item.const, options.length);
    if (!option) continue;
    pushOption({
      ...option,
      label: item.title || option.label,
    });
  }

  return options;
}

export function compactObject(
  values: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => value !== undefined),
  );
}
