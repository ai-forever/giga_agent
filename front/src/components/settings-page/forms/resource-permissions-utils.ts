import type { ResourcePermissionsDraft } from "./types";

export function normalizeIds(values: string[]): string[] {
  return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b));
}

export function normalizePermissions(
  value: ResourcePermissionsDraft,
): ResourcePermissionsDraft {
  return {
    read_user_ids: normalizeIds(value.read_user_ids),
    read_group_ids: normalizeIds(value.read_group_ids),
    public_read: Boolean(value.public_read),
  };
}

export function permissionsEqual(
  left: ResourcePermissionsDraft,
  right: ResourcePermissionsDraft,
): boolean {
  const a = normalizePermissions(left);
  const b = normalizePermissions(right);
  return (
    a.public_read === b.public_read &&
    JSON.stringify(a.read_user_ids) === JSON.stringify(b.read_user_ids) &&
    JSON.stringify(a.read_group_ids) === JSON.stringify(b.read_group_ids)
  );
}

export function hasNonDefaultPermissions(value: ResourcePermissionsDraft): boolean {
  const normalized = normalizePermissions(value);
  return (
    normalized.public_read ||
    normalized.read_user_ids.length > 0 ||
    normalized.read_group_ids.length > 0
  );
}

export function toPermissionsApiPayload(value: ResourcePermissionsDraft): {
  read_user_ids: string[];
  read_group_ids: string[];
  public_read: boolean;
} {
  const normalized = normalizePermissions(value);
  return {
    read_user_ids: normalized.read_user_ids,
    read_group_ids: normalized.read_group_ids,
    public_read: normalized.public_read,
  };
}

export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(
      ([a], [b]) => a.localeCompare(b),
    );
    return `{${entries
      .map(([key, val]) => `${JSON.stringify(key)}:${stableStringify(val)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}
