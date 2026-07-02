import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import type { FormMode } from "./connector-editor";
import type {
  ConnectorResponse,
  ConnectorType,
  ConnectorTypeMeta,
  JsonSchema,
  ResourcePermissionsDraft,
} from "./types";
import {
  EMPTY_RESOURCE_PERMISSIONS,
  MANAGED_CONNECTOR_TYPES,
  OPENAI_DEFAULT_BASE_URL,
  DEEPSEEK_DEFAULT_BASE_URL,
} from "./types";
import {
  hasNonDefaultPermissions,
  permissionsEqual,
  stableStringify,
  toPermissionsApiPayload,
} from "./resource-permissions-utils";
import { compactObject } from "./schema-fields-utils";

export interface UseConnectorEditorOptions {
  mode: FormMode;
  /**
   * Connector types this editor may create. When provided, the type list is
   * filtered to these (lowercased compare); when exactly one remains, the type
   * field is auto-selected and `hideTypeSelector` becomes true. Undefined =>
   * full list (the ConnectorsSettings page case).
   */
  allowedTypes?: string[];
  /** The connector being edited (edit mode only). */
  connector?: ConnectorResponse | null;
  canManagePermissions: boolean;
  /** Called after a successful create/edit with the fresh connector. */
  onSaved?: (connector: ConnectorResponse, mode: FormMode) => void;
}

const seedSettingsForType = (type: string): Record<string, unknown> => {
  if (type === "openai") return { base_url: OPENAI_DEFAULT_BASE_URL };
  if (type === "deepseek") return { base_url: DEEPSEEK_DEFAULT_BASE_URL };
  return {};
};

export const useConnectorEditor = ({
  mode,
  allowedTypes,
  connector,
  canManagePermissions,
  onSaved,
}: UseConnectorEditorOptions) => {
  const [connectorTypes, setConnectorTypes] = useState<ConnectorTypeMeta[]>([]);
  const [selectedType, setSelectedType] = useState(connector?.type || "");
  const [connectorName, setConnectorName] = useState(connector?.name || "");
  const [settingsValues, setSettingsValues] = useState<Record<string, unknown>>(
    (connector?.settings as Record<string, unknown>) || {},
  );
  const [settingsSchema, setSettingsSchema] = useState<JsonSchema | null>(null);
  const [isActive, setIsActive] = useState(connector?.is_active ?? true);
  const [checkConnection, setCheckConnection] = useState(true);

  const [loadingTypes, setLoadingTypes] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [loadingPermissions, setLoadingPermissions] = useState(false);
  const [saving, setSaving] = useState(false);

  const [createPermissions, setCreatePermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [editPermissions, setEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);
  const [initialEditPermissions, setInitialEditPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);

  const allowedLower = useMemo(
    () => (allowedTypes || []).map((type) => type.toLowerCase()),
    [allowedTypes],
  );

  const filteredTypes = useMemo(() => {
    if (!allowedTypes || allowedTypes.length === 0) return connectorTypes;
    return connectorTypes.filter((item) =>
      allowedLower.includes(item.type.toLowerCase()),
    );
  }, [connectorTypes, allowedTypes, allowedLower]);

  const hideTypeSelector = mode === "create" && filteredTypes.length === 1;

  const isManagedType = useMemo(
    () => MANAGED_CONNECTOR_TYPES.includes(selectedType as ConnectorType),
    [selectedType],
  );

  const applyType = useCallback((type: string) => {
    setSelectedType(type);
    setSettingsValues(seedSettingsForType(type));
  }, []);

  // Fetch connector type metadata once.
  useEffect(() => {
    let cancelled = false;
    setLoadingTypes(true);
    apiClient
      .get<ConnectorTypeMeta[]>(`${API_AGENT_PREFIX}/connectors/types/meta`)
      .then((data) => {
        if (!cancelled) setConnectorTypes(data);
      })
      .catch(() => {
        // handled globally
      })
      .finally(() => {
        if (!cancelled) setLoadingTypes(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // In create mode, auto-select the only allowed type (drives hideTypeSelector).
  useEffect(() => {
    if (mode !== "create") return;
    if (selectedType) return;
    if (filteredTypes.length === 1) {
      applyType(filteredTypes[0].type);
    }
  }, [mode, selectedType, filteredTypes, applyType]);

  // Load settings schema for custom (non-managed) types.
  useEffect(() => {
    if (!selectedType || isManagedType) {
      setSettingsSchema(null);
      setLoadingSchema(false);
      return;
    }

    let cancelled = false;
    setLoadingSchema(true);
    setSettingsSchema(null);

    apiClient
      .get<JsonSchema>(
        `${API_AGENT_PREFIX}/connectors/types/${selectedType}/settings-schema`,
      )
      .then((schema) => {
        if (!cancelled) setSettingsSchema(schema);
      })
      .catch(() => {
        if (!cancelled) setSettingsSchema(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingSchema(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isManagedType, selectedType]);

  // In edit mode, load the connector's resource permissions for superusers.
  useEffect(() => {
    if (mode !== "edit" || !connector || !canManagePermissions) return;

    let cancelled = false;
    setLoadingPermissions(true);
    apiClient
      .get<ResourcePermissionsDraft>(
        `${API_AGENT_PREFIX}/resource-permissions/connector/${connector.id}`,
      )
      .then((permissions) => {
        if (cancelled) return;
        setEditPermissions(permissions);
        setInitialEditPermissions(permissions);
      })
      .catch(() => {
        if (cancelled) return;
        setEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
        setInitialEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
      })
      .finally(() => {
        if (!cancelled) setLoadingPermissions(false);
      });

    return () => {
      cancelled = true;
    };
  }, [mode, connector, canManagePermissions]);

  const reset = useCallback(() => {
    setSelectedType("");
    setConnectorName("");
    setSettingsValues({});
    setSettingsSchema(null);
    setIsActive(true);
    setCheckConnection(true);
    setCreatePermissions(EMPTY_RESOURCE_PERMISSIONS);
    setEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setInitialEditPermissions(EMPTY_RESOURCE_PERMISSIONS);
    setLoadingPermissions(false);
  }, []);

  const submitDisabled =
    saving ||
    !selectedType ||
    (!isManagedType && loadingSchema) ||
    (mode === "edit" && canManagePermissions && loadingPermissions);

  const save = useCallback(async (): Promise<ConnectorResponse | null> => {
    if (!selectedType) return null;

    setSaving(true);
    try {
      const trimmedName = connectorName.trim();
      const compactedSettings = compactObject(settingsValues);

      if (mode === "edit" && connector) {
        const isResourceChanged =
          (connector.name || null) !== (trimmedName || null) ||
          connector.is_active !== isActive ||
          stableStringify(connector.settings || {}) !==
            stableStringify(compactedSettings);
        const isPermissionsChanged =
          canManagePermissions &&
          !permissionsEqual(editPermissions, initialEditPermissions);

        if (!isResourceChanged && !isPermissionsChanged) {
          toast.info("Изменений нет");
          return null;
        }

        let updated: ConnectorResponse = connector;
        if (isResourceChanged) {
          updated = await apiClient.patch<ConnectorResponse>(
            `${API_AGENT_PREFIX}/connectors/${connector.id}`,
            {
              name: trimmedName || null,
              settings: compactedSettings,
              is_active: isActive,
              check_connection: checkConnection,
            },
          );
        }
        if (isPermissionsChanged) {
          await apiClient.put(
            `${API_AGENT_PREFIX}/resource-permissions/connector/${connector.id}`,
            toPermissionsApiPayload(editPermissions),
          );
        }

        toast.success("Сервис обновлен");
        onSaved?.(updated, "edit");
        return updated;
      }

      const payload: Record<string, unknown> = {
        type: selectedType,
        settings: compactedSettings,
        is_active: isActive,
        check_connection: checkConnection,
      };
      if (trimmedName) {
        payload.name = trimmedName;
      }
      if (canManagePermissions && hasNonDefaultPermissions(createPermissions)) {
        payload.permissions = toPermissionsApiPayload(createPermissions);
      }

      const created = await apiClient.post<ConnectorResponse>(
        `${API_AGENT_PREFIX}/connectors`,
        payload,
      );
      toast.success("Сервис создан");
      onSaved?.(created, "create");
      return created;
    } catch {
      // handled globally
      return null;
    } finally {
      setSaving(false);
    }
  }, [
    mode,
    connector,
    selectedType,
    connectorName,
    settingsValues,
    isActive,
    checkConnection,
    canManagePermissions,
    createPermissions,
    editPermissions,
    initialEditPermissions,
    onSaved,
  ]);

  return {
    // state
    connectorTypes: filteredTypes,
    selectedType,
    connectorName,
    settingsValues,
    settingsSchema,
    isActive,
    checkConnection,
    hideTypeSelector,
    loadingTypes,
    loadingSchema,
    loadingPermissions,
    saving,
    submitDisabled,
    createPermissions,
    editPermissions,
    initialEditPermissions,
    // setters / handlers
    setSelectedType: applyType,
    setConnectorName,
    setSettingsValues,
    setIsActive,
    setCheckConnection,
    setCreatePermissions,
    setEditPermissions,
    save,
    reset,
  };
};

export default useConnectorEditor;
