import React from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { useRagContext } from "@/components/rag/providers/RAG";
import { getCollectionName } from "@/components/rag/hooks/use-rag";

interface CollectionsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const CollectionsModal: React.FC<CollectionsModalProps> = ({
  isOpen,
  onClose,
}) => {
  const {
    collections,
    activeCollections,
    activateCollection,
    deactivateCollection,
    collectionsLoading,
  } = useRagContext();

  const handleToggle = (collectionId: string, checked: boolean) => {
    if (checked) {
      activateCollection(collectionId);
    } else {
      deactivateCollection(collectionId);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="w-full max-w-3xl">
        <DialogHeader>
          <DialogTitle>Знания</DialogTitle>
          <DialogDescription>
            Активируйте коллекции из Базы Знаний, которые агент сможет
            использовать в своей работе
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-y-auto max-h-[60vh]">
          <div className="space-y-4">
            {collectionsLoading && (
              <div className="text-sm text-muted-foreground">
                Загрузка коллекций…
              </div>
            )}
            {!collectionsLoading && collections.length === 0 && (
              <div className="text-sm text-muted-foreground">
                Коллекции не найдены.
              </div>
            )}
            {!collectionsLoading &&
              collections.map((c) => {
                const enabled = Boolean(activeCollections[c.uuid]);
                return (
                  <div
                    key={c.uuid}
                    className={`bg-card border rounded-lg p-4 ${enabled ? "" : "opacity-50"}`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="min-w-0">
                        <div className="font-medium text-foreground truncate">
                          {getCollectionName(c.name)}
                        </div>
                        {c.metadata?.description && (
                          <div className="text-sm text-muted-foreground break-words">
                            {c.metadata.description}
                          </div>
                        )}
                      </div>
                      <Switch
                        checked={enabled}
                        onCheckedChange={(checked) =>
                          handleToggle(c.uuid, Boolean(checked))
                        }
                        aria-label={`Включить коллекцию ${c.name}`}
                      />
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default CollectionsModal;
