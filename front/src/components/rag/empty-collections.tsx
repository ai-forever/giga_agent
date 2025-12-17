import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FolderPlus, Layers } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useRagContext } from "@/components/rag/providers/RAG.tsx";
import { CreateCollectionDialog } from "@/components/rag/create-collection-dialog.tsx";

export default function EmptyCollectionsState() {
  const [open, setOpen] = useState(false);
  const { createCollection, setSelectedCollection } = useRagContext();

  const handleSubmit = async (name: string, description: string) => {
    const loadingToast = toast.loading("Создание коллекции", {
      richColors: true,
    });
    const newCollection = await createCollection(name, {
      description,
    });
    toast.dismiss(loadingToast);
    if (newCollection) {
      setOpen(false);
      toast.success("Коллекция успешно создана", {
        richColors: true,
      });
      setSelectedCollection(newCollection);
    } else {
      toast.warning(
        `Коллекция с названием '${name}' не может быть создана (скорее всего уже существует).`,
        {
          duration: 5000,
          richColors: true,
        },
      );
    }
  };

  return (
    <Card className="bg-muted/20 w-full mx-auto border-0 shadow-md">
      <CardContent className="flex flex-col items-center justify-center space-y-6 px-6 py-30 text-center">
        <div className="bg-primary/10 rounded-full p-4">
          <Layers className="text-primary h-12 w-12" />
        </div>

        <div className="max-w-md space-y-2">
          <h3 className="text-xl font-semibold tracking-tight">
            Коллекций пока нет
          </h3>
          <p className="text-muted-foreground">
            Коллекции помогают собрать документы и ресурсы в базу знаний.
            Создайте первую коллекцию, чтобы начать.
          </p>
        </div>

        <CreateCollectionDialog
          open={open}
          onOpenChange={setOpen}
          onSubmit={handleSubmit}
          trigger={
            <Button size="lg" className="mt-4 gap-2">
              <FolderPlus className="h-4 w-4" />
              Создать новую коллекцию
            </Button>
          }
        />
      </CardContent>
    </Card>
  );
}
