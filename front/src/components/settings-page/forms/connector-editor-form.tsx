import React from "react";
import ConnectorEditor, { type FormMode } from "./connector-editor";
import ResourcePermissions from "./resource-permissions";
import { useConnectorEditor } from "./use-connector-editor";
import type { ConnectorResponse } from "./types";

export interface ConnectorEditorFormProps {
  mode: FormMode;
  connector?: ConnectorResponse | null;
  /** Constrains creatable types (and hides the selector when only one). */
  allowedTypes?: string[];
  canManagePermissions: boolean;
  onSaved: (connector: ConnectorResponse, mode: FormMode) => void;
  onCancel: () => void;
}

/**
 * Connector create/edit subform: wires `useConnectorEditor` to the presentational
 * `ConnectorEditor` plus the permissions section. Shared by the connectors
 * settings page and the inline `ConnectorSelect` dialog. Mount fresh (e.g. via a
 * `key` or by rendering only when visible) so state re-seeds for each target.
 */
export const ConnectorEditorForm: React.FC<ConnectorEditorFormProps> = ({
  mode,
  connector = null,
  allowedTypes,
  canManagePermissions,
  onSaved,
  onCancel,
}) => {
  const editor = useConnectorEditor({
    mode,
    allowedTypes,
    connector,
    canManagePermissions,
    onSaved,
  });

  return (
    <ConnectorEditor
      mode={mode}
      connectorTypes={editor.connectorTypes}
      selectedType={editor.selectedType}
      connectorName={editor.connectorName}
      settingsValues={editor.settingsValues}
      settingsSchema={editor.settingsSchema}
      isActive={editor.isActive}
      checkConnection={editor.checkConnection}
      hideTypeSelector={editor.hideTypeSelector}
      loadingTypes={editor.loadingTypes}
      loadingSchema={editor.loadingSchema}
      saving={editor.saving}
      submitDisabled={editor.submitDisabled}
      onTypeChange={editor.setSelectedType}
      onConnectorNameChange={editor.setConnectorName}
      onSettingsChange={editor.setSettingsValues}
      onActiveChange={editor.setIsActive}
      onCheckConnectionChange={editor.setCheckConnection}
      onSubmit={() => void editor.save()}
      onCancel={onCancel}
      permissionsSection={
        canManagePermissions ? (
          mode === "edit" && connector ? (
            <ResourcePermissions
              mode="edit"
              resourceType="connector"
              resourceId={connector.id}
              value={editor.editPermissions}
              onChange={editor.setEditPermissions}
              canManage={canManagePermissions}
              disabled={editor.saving || editor.loadingPermissions}
            />
          ) : (
            <ResourcePermissions
              mode="create"
              resourceType="connector"
              value={editor.createPermissions}
              onChange={editor.setCreatePermissions}
              canManage={canManagePermissions}
              disabled={editor.saving}
            />
          )
        ) : undefined
      }
    />
  );
};

export default ConnectorEditorForm;
