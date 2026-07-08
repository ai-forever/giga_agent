import React, { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Loader2, Plus } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { toast } from "sonner";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { type FormMode } from "./connector-editor";
import ConnectorEditorForm from "./connector-editor-form";
import type { ConnectorResponse } from "./types";

const CREATE_SENTINEL = "__create__";
const NONE_SENTINEL = "__none__";

type SubformMode = "none" | "create" | "edit";

interface ConnectorSelectProps {
  /** Currently selected connector id ("" = none / not selected). */
  value: string;
  onValueChange: (connectorId: string) => void;
  /** Connector types this site allows. Drives both filtering and creatable types. */
  allowedTypes: string[];
  /** Render a "Без подключения" option (e.g. search engines that don't require one). */
  allowNone?: boolean;
  disabled?: boolean;
  loading?: boolean;
  id?: string;
  placeholder?: string;
  className?: string;
  /** Parent-owned connector list (already fetched with ?only_active=true). */
  connectors: ConnectorResponse[];
  /** Parent's refresh (re-fetch connectors) — called after create/edit. */
  onConnectorsChanged: () => void | Promise<void>;
  canManagePermissions: boolean;
}

const expandTransition = { duration: 0.22, ease: "easeInOut" as const };

export const ConnectorSelect: React.FC<ConnectorSelectProps> = ({
  value,
  onValueChange,
  allowedTypes,
  allowNone = false,
  disabled,
  loading,
  id,
  placeholder = "Выберите подключение",
  className,
  connectors,
  onConnectorsChanged,
  canManagePermissions,
}) => {
  const [subform, setSubform] = useState<SubformMode>("none");

  // Track whether the connector list has finished loading at least once, so the
  // create subform only auto-opens once we actually know the list is empty —
  // not during the initial render before the parent's fetch has started.
  const [connectorsLoaded, setConnectorsLoaded] = useState(false);
  const wasLoadingRef = useRef(loading);
  useEffect(() => {
    if (wasLoadingRef.current && !loading) {
      setConnectorsLoaded(true);
    }
    wasLoadingRef.current = loading;
  }, [loading]);

  const allowedLower = useMemo(
    () => allowedTypes.map((type) => type.toLowerCase()),
    [allowedTypes],
  );

  const filteredConnectors = useMemo(
    () =>
      connectors.filter((connector) =>
        allowedLower.includes((connector.type || "").toLowerCase()),
      ),
    [connectors, allowedLower],
  );

  const selectedConnector = useMemo(
    () => filteredConnectors.find((connector) => connector.id === value),
    [filteredConnectors, value],
  );

  const canEditSelected = Boolean(selectedConnector?.can_edit);
  const interactive = !disabled && !loading;
  // When a connector is required but there is nothing to pick, the create form
  // is the only sensible affordance — surface it once the list has loaded.
  const forceCreate =
    interactive &&
    connectorsLoaded &&
    !allowNone &&
    filteredConnectors.length === 0;
  const showCreate = forceCreate || subform === "create";
  const showEdit = subform === "edit" && !!selectedConnector && interactive;

  // Auto-select the first compatible connector when one is required but none is
  // chosen yet (so dependent data — e.g. model lists — loads without an extra click).
  useEffect(() => {
    if (!interactive || allowNone || value) return;
    if (filteredConnectors.length > 0) {
      onValueChange(filteredConnectors[0].id);
    }
  }, [interactive, allowNone, value, filteredConnectors, onValueChange]);

  const handleSelect = (next: string) => {
    if (next === CREATE_SENTINEL) {
      setSubform("create");
      return;
    }
    if (next === NONE_SENTINEL) {
      onValueChange("");
      setSubform("none");
      return;
    }
    onValueChange(next);
    setSubform("none");
  };

  const handleSaved = async (saved: ConnectorResponse, savedMode: FormMode) => {
    await onConnectorsChanged();
    if (saved.is_active) {
      // Keep the inline form open after saving: select the connector and show
      // it in edit mode (a freshly created one is now an editable connector).
      onValueChange(saved.id);
      setSubform("edit");
    } else if (savedMode === "create") {
      toast.info(
        "Подключение создано, но неактивно — активируйте его, чтобы выбрать",
      );
    }
  };

  const selectValue = showCreate
    ? CREATE_SENTINEL
    : value || (allowNone ? NONE_SENTINEL : "");

  return (
    <div className={className}>
      <div className="space-y-2">
        <Select
          value={selectValue}
          onValueChange={handleSelect}
          disabled={disabled || loading}
        >
          <SelectTrigger id={id} className="w-full">
            {loading ? (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Загрузка подключений...
              </div>
            ) : (
              <SelectValue placeholder={placeholder} />
            )}
          </SelectTrigger>
          <SelectContent>
            {allowNone && (
              <SelectItem value={NONE_SENTINEL}>Без подключения</SelectItem>
            )}
            {filteredConnectors.map((connector) => (
              <SelectItem key={connector.id} value={connector.id}>
                {connector.name || connector.type}
              </SelectItem>
            ))}
            {(allowNone || filteredConnectors.length > 0) && (
              <SelectSeparator />
            )}
            <SelectItem value={CREATE_SENTINEL}>
              <span className="flex items-center gap-2">
                <Plus className="size-4" />
                Создать подключение
              </span>
            </SelectItem>
          </SelectContent>
        </Select>

        {selectedConnector && canEditSelected && subform !== "create" && (
          <button
            type="button"
            onClick={() =>
              setSubform((prev) => (prev === "edit" ? "none" : "edit"))
            }
            className="flex items-center gap-2 w-full py-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <div className="flex-1 h-px bg-border" />
            <span className="flex items-center gap-1.5">
              Отредактировать подключение
              <ChevronDown
                className={`size-4 transition-transform ${showEdit ? "rotate-180" : ""}`}
              />
            </span>
            <div className="flex-1 h-px bg-border" />
          </button>
        )}

        <AnimatePresence initial={false}>
          {showCreate && (
            <motion.div
              key="create"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={expandTransition}
              className="overflow-hidden"
            >
              <div className="space-y-4 rounded-md border border-border p-4">
                <h4 className="text-sm font-medium">Новое подключение</h4>
                <ConnectorEditorForm
                  key="create"
                  mode="create"
                  connector={null}
                  allowedTypes={allowedTypes}
                  canManagePermissions={canManagePermissions}
                  onSaved={handleSaved}
                  onCancel={() => setSubform("none")}
                />
              </div>
            </motion.div>
          )}

          {showEdit && selectedConnector && (
            <motion.div
              key="edit"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={expandTransition}
              className="overflow-hidden"
            >
              <div className="space-y-4 rounded-md border border-border p-4">
                <h4 className="text-sm font-medium">
                  Редактирование:{" "}
                  {selectedConnector.name || selectedConnector.type}
                </h4>
                <ConnectorEditorForm
                  key={selectedConnector.id}
                  mode="edit"
                  connector={selectedConnector}
                  allowedTypes={allowedTypes}
                  canManagePermissions={canManagePermissions}
                  onSaved={handleSaved}
                  onCancel={() => setSubform("none")}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};

export default ConnectorSelect;
