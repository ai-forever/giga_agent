"use client";

import type React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { FolderPlus, AlertCircle } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { DESCRIPTION_MAX_LENGTH } from "@/constants";
import { useState } from "react";

interface CreateCollectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger?: React.ReactNode;
  onSubmit: (name: string, description: string) => Promise<void>;
}

export function CreateCollectionDialog({
  open,
  onOpenChange,
  trigger,
  onSubmit,
}: CreateCollectionDialogProps) {
  const [loading, setLoading] = useState(false);
  const [newCollectionName, setNewCollectionName] = useState("");
  const [newCollectionDescription, setNewCollectionDescription] = useState("");

  const isDescriptionTooLong =
    newCollectionDescription.length > DESCRIPTION_MAX_LENGTH;

  const handleSubmit = async () => {
    setLoading(true);
    await onSubmit(newCollectionName, newCollectionDescription);
    setNewCollectionName("");
    setNewCollectionDescription("");
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="outline" size="icon">
            <FolderPlus className="h-4 w-4" />
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Создать новую коллекцию</DialogTitle>
          <DialogDescription>Введите название коллекции</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid grid-cols-4 items-center gap-4">
            <Label htmlFor="collection-name" className="text-right">
              Название
            </Label>
            <Input
              id="collection-name"
              value={newCollectionName}
              onChange={(e) => setNewCollectionName(e.target.value)}
              className="col-span-3"
            />
          </div>
          <div className="grid grid-cols-4 items-start gap-4">
            <Label htmlFor="collection-description" className="text-right">
              Описание
            </Label>
            <div className="col-span-3 space-y-2">
              <Textarea
                id="collection-description"
                value={newCollectionDescription}
                onChange={(e) => setNewCollectionDescription(e.target.value)}
              />
              <div className="text-muted-foreground text-right text-xs">
                {newCollectionDescription.length}/{DESCRIPTION_MAX_LENGTH}{" "}
                символов
              </div>
            </div>
          </div>
          {isDescriptionTooLong && (
            <div className="mt-2">
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  Описание превышает максимальное количество(
                  {DESCRIPTION_MAX_LENGTH}) разрешенных символов.
                </AlertDescription>
              </Alert>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button
            onClick={handleSubmit}
            disabled={
              !newCollectionName.trim() || isDescriptionTooLong || loading
            }
          >
            Создать
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
