import { Collection } from "@/types/collection";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { MoreVertical } from "lucide-react";
import { EditCollectionDialog } from "./edit-collection-dialog";
import { DeleteCollectionAlert } from "./delete-collection-alert";
import { CollectionPermissionsDialog } from "./collection-permissions-dialog";

export function CollectionActions({
  collection,
  onDelete,
  onEdit,
  canManagePermissions,
}: {
  collection: Collection;
  onDelete: (id: string) => void;
  onEdit: (
    id: string,
    name: string,
    metadata: Record<string, any>,
  ) => Promise<void>;
  canManagePermissions: boolean;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild onClick={(e) => e.stopPropagation()}>
        <Button variant="ghost" size="icon" className="h-6 w-6">
          <MoreVertical className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-48 p-1" align="end">
        <div className="flex flex-col space-y-1">
          <EditCollectionDialog
            collection={collection}
            handleEditCollection={onEdit}
          />
          {canManagePermissions && (
            <CollectionPermissionsDialog collection={collection} />
          )}
          <DeleteCollectionAlert collection={collection} onDelete={onDelete} />
        </div>
      </PopoverContent>
    </Popover>
  );
}
