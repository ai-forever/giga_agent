import React, { useEffect, useMemo, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Trash2, Plus } from "lucide-react";
import { z } from "zod";
import { useSettings } from "@/components/Settings";
import { Secret } from "@/interfaces.ts";

type SecretItem = Secret & {
  id: string;
};

export type ContextModalData = {
  instructions: string;
  secrets: Array<Secret>;
};

interface ContextModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave?: (data: ContextModalData) => void;
  defaultInstructions?: string;
  defaultSecrets?: Array<Secret>;
}

const secretSchema = z.object({
  name: z.string().trim().min(1, "Заполните название"),
  value: z.string().trim().min(1, "Заполните значение"),
  description: z.string().optional(),
});

const secretsArraySchema = z.array(secretSchema).superRefine((items, ctx) => {
  const seen = new Map<string, number[]>();
  items.forEach((item, index) => {
    const key = item.name.trim().toLowerCase();
    if (!seen.has(key)) seen.set(key, []);
    seen.get(key)!.push(index);
  });
  for (const [, indices] of seen) {
    if (indices.length > 1) {
      indices.forEach((i) => {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Названия секретов должны быть уникальными",
          path: [i, "name"],
        });
      });
    }
  }
});

const ContextModal: React.FC<ContextModalProps> = ({
  isOpen,
  onClose,
  onSave,
  defaultInstructions = "",
  defaultSecrets = [],
}) => {
  const { settings, setSettings } = useSettings();
  const [instructions, setInstructions] = useState<string>(defaultInstructions);
  const [secrets, setSecrets] = useState<SecretItem[]>(
    defaultSecrets.map((s) => ({
      id: crypto.randomUUID(),
      ...s,
    })),
  );
  const [errors, setErrors] = useState<Record<string, Record<string, string>>>(
    {},
  );
  const [generalError, setGeneralError] = useState<string>("");

  // Загрузка значений из Settings при открытии модалки
  useEffect(() => {
    if (!isOpen) return;
    try {
      const loadedInstructions = settings?.contextInstructions ?? "";
      const loadedSecrets = settings?.contextSecrets ?? [];
      setInstructions(loadedInstructions);
      setSecrets(
        (loadedSecrets || []).map((s) => ({
          id: crypto.randomUUID(),
          ...s,
        })),
      );
    } catch {
      // ignore
    }
    // не добавляем зависимости, чтобы инициализировать при каждом открытии
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const parsedForValidation = useMemo(
    () =>
      secrets.map((s) => ({
        name: s.name ?? "",
        value: s.value ?? "",
        description: s.description ?? "",
      })),
    [secrets],
  );

  const validate = (): boolean => {
    setGeneralError("");
    setErrors({});
    const result = secretsArraySchema.safeParse(parsedForValidation);
    if (result.success) return true;

    const fieldErrors: Record<string, Record<string, string>> = {};
    for (const issue of result.error.issues) {
      // path: [index, "field"]
      if (
        Array.isArray(issue.path) &&
        issue.path.length === 2 &&
        typeof issue.path[0] === "number" &&
        typeof issue.path[1] === "string"
      ) {
        const index = issue.path[0] as number;
        const field = issue.path[1] as string;
        const id = secrets[index]?.id;
        if (!id) continue;
        if (!fieldErrors[id]) fieldErrors[id] = {};
        fieldErrors[id][field] = issue.message;
      } else {
        setGeneralError(issue.message);
      }
    }
    setErrors(fieldErrors);
    return false;
  };

  const handleSave = () => {
    if (!validate()) return;
    const payload: ContextModalData = {
      instructions,
      secrets: secrets.map(({ id, ...rest }) => rest),
    };
    // Сохранение в Settings
    setSettings({
      ...settings,
      contextInstructions: payload.instructions,
      contextSecrets: payload.secrets,
    });
    if (onSave) onSave(payload);
    onClose();
  };

  const addSecret = () => {
    setSecrets((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        name: "",
        value: "",
        description: "",
      },
    ]);
  };

  const removeSecret = (id: string) => {
    setSecrets((prev) => prev.filter((s) => s.id !== id));
    setErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };

  const updateSecret = <K extends keyof SecretItem>(
    id: string,
    key: K,
    value: SecretItem[K],
  ) => {
    setSecrets((prev) =>
      prev.map((s) => (s.id === id ? { ...s, [key]: value } : s)),
    );
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="w-full max-w-3xl">
        <DialogHeader>
          <DialogTitle>Контекст</DialogTitle>
          <DialogDescription>
            Настройте поведение агента под себя
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-y-auto max-h-[60vh]">
          <div className="space-y-6">
            <hr className="my-2 mt-0" />
            <section className="space-y-2">
              <h3 className="font-medium text-sm">Доп. инструкции</h3>
              <p className="text-sm text-muted-foreground">
                Укажите дополнительные инструкции по поведению агента
              </p>
              <Textarea
                placeholder="Опишите предпочитаемый стиль, ограничения, тон и т.п."
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                className="min-h-28 max-h-67"
              />
            </section>

            <hr className="my-2" />

            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-medium text-sm">Секреты</h3>
                  <p className="text-sm text-muted-foreground">
                    Здесь хранятся секретные значения: Credentials, AuthTokens и
                    т.д.
                  </p>
                </div>
                <Button type="button" variant={"outline"} onClick={addSecret}>
                  <Plus size={16} />
                  Добавить секрет
                </Button>
              </div>

              {generalError && (
                <div className="text-sm text-destructive">{generalError}</div>
              )}

              <div className="space-y-4">
                {secrets.length === 0 && (
                  <div className="text-sm text-muted-foreground">
                    Секреты пока не добавлены.
                  </div>
                )}
                {secrets.map((s) => {
                  const err = errors[s.id] || {};
                  return (
                    <div
                      key={s.id}
                      className="border rounded-lg p-3 bg-muted/40"
                    >
                      <div className="flex items-start gap-2">
                        <div className="flex-1 grid grid-cols-2 gap-2">
                          <div>
                            <Input
                              placeholder="Название"
                              value={s.name}
                              onChange={(e) =>
                                updateSecret(s.id, "name", e.target.value)
                              }
                              aria-invalid={Boolean(err.name)}
                            />
                            {err.name && (
                              <div className="mt-1 text-xs text-destructive">
                                {err.name}
                              </div>
                            )}
                          </div>
                          <div>
                            <Input
                              placeholder="Значение"
                              value={s.value}
                              onChange={(e) =>
                                updateSecret(s.id, "value", e.target.value)
                              }
                              style={
                                {
                                  WebkitTextSecurity: "disc",
                                  textSecurity: "disc",
                                } as React.CSSProperties
                              }
                              aria-invalid={Boolean(err.value)}
                            />
                            {err.value && (
                              <div className="mt-1 text-xs text-destructive">
                                {err.value}
                              </div>
                            )}
                          </div>
                        </div>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="Удалить секрет"
                          onClick={() => removeSecret(s.id)}
                          title="Удалить секрет"
                        >
                          <Trash2 size={16} />
                        </Button>
                      </div>

                      <div className="mt-2">
                        <Input
                          placeholder="Описание (где/как применять секрет)"
                          value={s.description ?? ""}
                          onChange={(e) =>
                            updateSecret(s.id, "description", e.target.value)
                          }
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 pt-2">
          <Button variant="ghost" type="button" onClick={onClose}>
            Отмена
          </Button>
          <Button type="button" onClick={handleSave}>
            Сохранить
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default ContextModal;
