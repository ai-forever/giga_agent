import { useEffect, useState } from "react";
import { Shield } from "lucide-react";
import { toast } from "sonner";

import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import ResourcePermissions from "@/components/settings-page/forms/resource-permissions";
import type { Collection } from "@/types/collection";
import type { ResourcePermissionsDraft } from "@/components/settings-page/forms/types";
import { EMPTY_RESOURCE_PERMISSIONS } from "@/components/settings-page/forms/types";
import {
  permissionsEqual,
  toPermissionsApiPayload,
} from "@/components/settings-page/forms/resource-permissions-utils";

export function CollectionPermissionsDialog({
  collection,
}: {
  collection: Collection;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [permissions, setPermissions] = useState<ResourcePermissionsDraft>(
    EMPTY_RESOURCE_PERMISSIONS,
  );
  const [initialPermissions, setInitialPermissions] =
    useState<ResourcePermissionsDraft>(EMPTY_RESOURCE_PERMISSIONS);

  useEffect(() => {
    if (!open) {
      return;
    }
    setLoading(true);
    void apiClient
      .get<ResourcePermissionsDraft>(
        `${API_AGENT_PREFIX}/resource-permissions/rag_collection/${collection.uuid}`,
      )
      .then((payload) => {
        setPermissions(payload);
        setInitialPermissions(payload);
      })
      .catch(() => {
        setPermissions(EMPTY_RESOURCE_PERMISSIONS);
        setInitialPermissions(EMPTY_RESOURCE_PERMISSIONS);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [collection.uuid, open]);

  const hasChanges = !permissionsEqual(permissions, initialPermissions);

  const handleSave = async () => {
    if (!hasChanges || saving) return;
    try {
      setSaving(true);
      await apiClient.put(
        `${API_AGENT_PREFIX}/resource-permissions/rag_collection/${collection.uuid}`,
        toPermissionsApiPayload(permissions),
      );
      setInitialPermissions(permissions);
      toast.success("Права доступа обновлены");
      setOpen(false);
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start px-2 py-1.5 text-sm"
          onClick={(e) => e.stopPropagation()}
        >
          <Shield className="mr-2 h-4 w-4" />
          <span>Права доступа</span>
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Права доступа к папке</DialogTitle>
          <DialogDescription>
            Настройте, кто может читать коллекцию.
          </DialogDescription>
        </DialogHeader>

        <ResourcePermissions
          mode="edit"
          resourceType="rag_collection"
          resourceId={collection.uuid}
          value={permissions}
          onChange={setPermissions}
          canManage
          disabled={loading || saving}
          defaultOpen
        />

        <DialogFooter>
          <Button
            onClick={handleSave}
            disabled={loading || saving || !hasChanges}
          >
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
