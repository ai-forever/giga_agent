import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Loader2, Pencil, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { API_AGENT_PREFIX } from "@/config.ts";
import { useConfirm } from "@/components/providers/confirm.tsx";
import { apiClient } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import SchemaFields from "./forms/schema-fields";
import type {
  ChannelBotResponse,
  ChannelContactResponse,
  ChannelTypeMeta,
  JsonSchema,
} from "./forms/types";
import { compactObject } from "./forms/schema-fields-utils";

const areContactsEqual = (
  left: ChannelContactResponse[],
  right: ChannelContactResponse[],
): boolean => {
  if (left.length !== right.length) {
    return false;
  }

  return left.every((contact, index) => {
    const other = right[index];
    return (
      contact.id === other?.id &&
      contact.bot_id === other.bot_id &&
      contact.external_chat_id === other.external_chat_id &&
      contact.external_user_id === other.external_user_id &&
      contact.chat_type === other.chat_type &&
      contact.chat_title === other.chat_title &&
      contact.username === other.username &&
      contact.first_name === other.first_name &&
      contact.last_name === other.last_name &&
      contact.is_approved === other.is_approved &&
      contact.created_at === other.created_at &&
      contact.updated_at === other.updated_at
    );
  });
};

const formatChannelName = (bot: ChannelBotResponse): string => {
  if (bot.bot_username?.trim()) {
    return `@${bot.bot_username.trim()}`;
  }
  return `${bot.channel_type} • ${bot.id.slice(0, 8)}`;
};

const formatContactName = (contact: ChannelContactResponse): string => {
  if (contact.chat_title?.trim()) {
    return contact.chat_title.trim();
  }

  const parts = [contact.first_name, contact.last_name]
    .map((value) => value?.trim())
    .filter(Boolean);
  if (parts.length > 0) {
    return parts.join(" ");
  }

  if (contact.username?.trim()) {
    return `@${contact.username.trim()}`;
  }

  return contact.external_chat_id;
};

const formatContactMeta = (contact: ChannelContactResponse): string => {
  const parts = [`chat_id: ${contact.external_chat_id}`];
  if (contact.external_user_id) {
    parts.push(`user_id: ${contact.external_user_id}`);
  }
  if (contact.chat_type) {
    parts.push(contact.chat_type);
  }
  return parts.join(" • ");
};

const ContactsSection: React.FC<{
  botId: string;
  contacts: ChannelContactResponse[];
  loading: boolean;
  actionKey: string | null;
  onApproveToggle: (contact: ChannelContactResponse, approve: boolean) => Promise<void>;
  onDelete: (contact: ChannelContactResponse) => Promise<void>;
}> = ({ botId, contacts, loading, actionKey, onApproveToggle, onDelete }) => {
  if (!botId) return null;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin mr-2" />
        Загрузка контактов...
      </div>
    );
  }

  if (contacts.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Контактов пока нет. Они появятся, когда кто-то напишет этому боту.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {contacts.map((contact) => {
        const approveKey = `approve:${contact.id}`;
        const deleteKey = `delete:${contact.id}`;
        const isApproving = actionKey === approveKey;
        const isDeleting = actionKey === deleteKey;

        return (
          <div
            key={contact.id}
            className="flex items-start gap-3 rounded-xl border border-border bg-card/70 p-3"
          >
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{formatContactName(contact)}</span>
                <Badge variant={contact.is_approved ? "default" : "secondary"}>
                  {contact.is_approved ? "Подтверждён" : "Ожидает"}
                </Badge>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {formatContactMeta(contact)}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {!contact.is_approved ? (
                <Button
                  size="sm"
                  disabled={isApproving || isDeleting}
                  onClick={() => void onApproveToggle(contact, true)}
                >
                  {isApproving ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <>
                      <Check className="mr-1 size-4" />
                      Подтвердить
                    </>
                  )}
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={isApproving || isDeleting}
                  onClick={() => void onApproveToggle(contact, false)}
                >
                  {isApproving ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <>
                      <X className="mr-1 size-4" />
                      Отозвать
                    </>
                  )}
                </Button>
              )}
              <Button
                size="icon"
                variant="ghost"
                disabled={isApproving || isDeleting}
                onClick={() => void onDelete(contact)}
                title="Удалить контакт"
              >
                {isDeleting ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Trash2 className="size-4 text-destructive" />
                )}
              </Button>
            </div>
          </div>
        );
      })}
    </div>
  );
};

interface ChannelFormProps {
  mode: "create" | "edit";
  selectedType: string;
  channelTypes: ChannelTypeMeta[];
  loadingTypes: boolean;
  loadingSchema: boolean;
  saving: boolean;
  settingsSchema: JsonSchema | null;
  settingsValues: Record<string, unknown>;
  isEnabled: boolean;
  submitDisabled: boolean;
  onTypeChange: (value: string) => void;
  onSettingsChange: (values: Record<string, unknown>) => void;
  onEnabledChange: (value: boolean) => void;
  onSubmit: () => void;
  onCancel: () => void;
}

const ChannelForm: React.FC<ChannelFormProps> = ({
  mode,
  selectedType,
  channelTypes,
  loadingTypes,
  loadingSchema,
  saving,
  settingsSchema,
  settingsValues,
  isEnabled,
  submitDisabled,
  onTypeChange,
  onSettingsChange,
  onEnabledChange,
  onSubmit,
  onCancel,
}) => {
  return (
    <div className="space-y-5">
      <div className="space-y-1.5">
        <Label htmlFor="channel-type">
          Тип канала <span className="text-destructive">*</span>
        </Label>
        {mode === "edit" ? (
          <Input id="channel-type" value={selectedType} disabled />
        ) : (
          <Select
            value={selectedType}
            onValueChange={onTypeChange}
            disabled={loadingTypes || saving}
          >
            <SelectTrigger id="channel-type" className="w-full">
              {loadingTypes ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Загрузка типов...
                </div>
              ) : (
                <SelectValue placeholder="Выберите тип канала" />
              )}
            </SelectTrigger>
            <SelectContent>
              {channelTypes.map((item) => (
                <SelectItem key={item.type} value={item.type}>
                  {item.type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {selectedType && (
        <div className="space-y-2">
          <Label>Настройки канала</Label>
          {loadingSchema ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Загрузка схемы настроек...
            </div>
          ) : (
            <SchemaFields
              schema={settingsSchema || {}}
              values={settingsValues}
              onChange={onSettingsChange}
              disabled={saving}
              idPrefix={`channel-setting-${mode}`}
            />
          )}
        </div>
      )}

      <div className="flex items-center justify-between rounded-lg border border-border bg-card/60 p-3">
        <div>
          <Label htmlFor={`channel-enabled-${mode}`}>Статус канала</Label>
          <p className="text-xs text-muted-foreground">
            На этом этапе показываем только persisted состояние из `is_enabled`.
          </p>
        </div>
        <Switch
          id={`channel-enabled-${mode}`}
          checked={isEnabled}
          onCheckedChange={onEnabledChange}
          disabled={saving}
        />
      </div>

      <div className="flex gap-2 pt-2">
        <Button onClick={onSubmit} disabled={submitDisabled}>
          {saving ? (
            <>
              <Loader2 className="mr-2 size-4 animate-spin" />
              Сохранение...
            </>
          ) : mode === "edit" ? (
            "Сохранить"
          ) : (
            "Создать"
          )}
        </Button>
        <Button variant="outline" onClick={onCancel} disabled={saving}>
          Отмена
        </Button>
      </div>
    </div>
  );
};

export const ChannelsSettings: React.FC = () => {
  const confirm = useConfirm();

  const [bots, setBots] = useState<ChannelBotResponse[]>([]);
  const [channelTypes, setChannelTypes] = useState<ChannelTypeMeta[]>([]);
  const [contacts, setContacts] = useState<ChannelContactResponse[]>([]);

  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [editingBotId, setEditingBotId] = useState<string | null>(null);

  const [selectedType, setSelectedType] = useState("");
  const [settingsSchema, setSettingsSchema] = useState<JsonSchema | null>(null);
  const [settingsValues, setSettingsValues] = useState<Record<string, unknown>>({});
  const [isEnabled, setIsEnabled] = useState(true);

  const [loadingBots, setLoadingBots] = useState(false);
  const [loadingTypes, setLoadingTypes] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [loadingDialogData, setLoadingDialogData] = useState(false);
  const [loadingContacts, setLoadingContacts] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingBotId, setDeletingBotId] = useState<string | null>(null);
  const [contactActionKey, setContactActionKey] = useState<string | null>(null);

  const isEditMode = editingBotId !== null;
  const isEditorVisible = isCreatingNew || isEditMode;

  const editingBot = useMemo(
    () => bots.find((bot) => bot.id === editingBotId) || null,
    [bots, editingBotId],
  );

  const fetchBots = useCallback(async () => {
    setLoadingBots(true);
    try {
      const data = await apiClient.get<ChannelBotResponse[]>(
        `${API_AGENT_PREFIX}/channels`,
      );
      setBots(data);
    } catch {
      // handled globally
    } finally {
      setLoadingBots(false);
    }
  }, []);

  const fetchChannelTypes = useCallback(async () => {
    setLoadingTypes(true);
    try {
      const data = await apiClient.get<ChannelTypeMeta[]>(
        `${API_AGENT_PREFIX}/channels/types/meta`,
      );
      setChannelTypes(data);
    } catch {
      // handled globally
    } finally {
      setLoadingTypes(false);
    }
  }, []);

  const fetchContacts = useCallback(
    async (botId: string, options?: { silent?: boolean }) => {
      const silent = options?.silent ?? false;
      if (!silent) {
        setLoadingContacts(true);
      }

      try {
        const data = await apiClient.get<ChannelContactResponse[]>(
          `${API_AGENT_PREFIX}/channels/${botId}/contacts`,
        );
        setContacts((current) =>
          areContactsEqual(current, data) ? current : data,
        );
      } catch {
        // handled globally
      } finally {
        if (!silent) {
          setLoadingContacts(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    void fetchBots();
    void fetchChannelTypes();
  }, [fetchBots, fetchChannelTypes]);

  useEffect(() => {
    if (!isEditorVisible || !selectedType) {
      setSettingsSchema(null);
      setLoadingSchema(false);
      return;
    }

    let cancelled = false;
    setLoadingSchema(true);
    setSettingsSchema(null);

    const run = async () => {
      try {
        const schema = await apiClient.get<JsonSchema>(
          `${API_AGENT_PREFIX}/channels/types/${selectedType}/settings-schema`,
        );
        if (!cancelled) {
          setSettingsSchema(schema);
        }
      } catch {
        if (!cancelled) {
          setSettingsSchema(null);
        }
      } finally {
        if (!cancelled) {
          setLoadingSchema(false);
        }
      }
    };

    void run();

    return () => {
      cancelled = true;
    };
  }, [isEditorVisible, selectedType]);

  useEffect(() => {
    if (!editingBotId) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void fetchContacts(editingBotId, { silent: true });
    }, 10_000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [editingBotId, fetchContacts]);

  const resetEditorState = useCallback(() => {
    setIsCreatingNew(false);
    setEditingBotId(null);
    setSelectedType("");
    setSettingsSchema(null);
    setSettingsValues({});
    setIsEnabled(true);
    setContacts([]);
    setLoadingContacts(false);
    setLoadingDialogData(false);
    setContactActionKey(null);
  }, []);

  const closeEditor = useCallback(() => {
    if (saving) return;
    resetEditorState();
  }, [resetEditorState, saving]);

  const handleStartCreate = () => {
    resetEditorState();
    setIsCreatingNew(true);
  };

  const handleStartEdit = async (botId: string) => {
    setIsCreatingNew(false);
    setLoadingDialogData(true);
    setContacts([]);
    setEditingBotId(botId);

    try {
      const [botData] = await Promise.all([
        apiClient.get<ChannelBotResponse>(`${API_AGENT_PREFIX}/channels/${botId}`),
        fetchContacts(botId),
      ]);
      setEditingBotId(botData.id);
      setSelectedType(botData.channel_type);
      setSettingsValues(botData.settings || {});
      setIsEnabled(botData.is_enabled);
    } catch {
      resetEditorState();
    } finally {
      setLoadingDialogData(false);
    }
  };

  const handleDeleteBot = async (botId: string) => {
    const bot = bots.find((item) => item.id === botId);
    if (!bot) return;

    if (
      !(await confirm({
        title: "Удалить бота",
        description: `Удалить ${formatChannelName(bot)}? Это также удалит связанные контакты.`,
        confirmText: "Удалить",
        variant: "destructive",
      }))
    ) {
      return;
    }

    setDeletingBotId(botId);
    try {
      await apiClient.delete(`${API_AGENT_PREFIX}/channels/${botId}`);
      toast.success("Бот удалён");
      if (editingBotId === botId) {
        closeEditor();
      }
      await fetchBots();
    } catch {
      // handled globally
    } finally {
      setDeletingBotId(null);
    }
  };

  const handleSave = async () => {
    if (!selectedType) {
      toast.error("Выберите тип канала");
      return;
    }

    setSaving(true);
    try {
      const compactedSettings = compactObject(settingsValues);

      if (isEditMode && editingBotId) {
        await apiClient.patch<ChannelBotResponse>(
          `${API_AGENT_PREFIX}/channels/${editingBotId}`,
          {
            settings: compactedSettings,
            is_enabled: isEnabled,
          },
        );
        toast.success("Настройки бота обновлены");
      } else {
        await apiClient.post<ChannelBotResponse>(`${API_AGENT_PREFIX}/channels`, {
          channel_type: selectedType,
          settings: compactedSettings,
          is_enabled: isEnabled,
        });
        toast.success("Бот создан");
      }

      await fetchBots();
      closeEditor();
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleApproveToggle = async (
    contact: ChannelContactResponse,
    approve: boolean,
  ) => {
    if (!editingBotId) return;

    const actionKey = `approve:${contact.id}`;
    setContactActionKey(actionKey);
    try {
      const search = contact.external_user_id
        ? `?external_user_id=${encodeURIComponent(contact.external_user_id)}`
        : "";
      await apiClient.patch<ChannelContactResponse>(
        `${API_AGENT_PREFIX}/channels/${editingBotId}/contacts/by-chat/${encodeURIComponent(contact.external_chat_id)}${search}`,
        { is_approved: approve },
      );
      toast.success(approve ? "Контакт подтверждён" : "Доступ отозван");
      await fetchContacts(editingBotId);
    } catch {
      // handled globally
    } finally {
      setContactActionKey(null);
    }
  };

  const handleDeleteContact = async (contact: ChannelContactResponse) => {
    if (!editingBotId) return;

    if (
      !(await confirm({
        title: "Удалить контакт",
        description:
          "Удалить этот контакт? Пользователю придется написать боту заново.",
        confirmText: "Удалить",
        variant: "destructive",
      }))
    ) {
      return;
    }

    const actionKey = `delete:${contact.id}`;
    setContactActionKey(actionKey);
    try {
      await apiClient.delete(
        `${API_AGENT_PREFIX}/channels/${editingBotId}/contacts/${contact.id}`,
      );
      toast.success("Контакт удалён");
      await fetchContacts(editingBotId);
    } catch {
      // handled globally
    } finally {
      setContactActionKey(null);
    }
  };

  const submitDisabled =
    saving || loadingDialogData || loadingSchema || !selectedType;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="font-medium">Каналы</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Управление ботами разных типов через единый API каналов.
          </p>
        </div>
        <Button
          onClick={handleStartCreate}
          size="sm"
          variant="default2"
          disabled={isCreatingNew || saving}
        >
          <Plus className="mr-2 size-4" />
          Создать
        </Button>
      </div>

      {isCreatingNew && (
        <div className="rounded-xl border border-border bg-muted/20 p-4">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h4 className="font-medium">Новый канал</h4>
              <p className="mt-1 text-sm text-muted-foreground">
                Выберите тип канала и заполните динамические поля его настройки.
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={closeEditor}
              disabled={saving}
            >
              <X className="size-4" />
            </Button>
          </div>
          <ChannelForm
            mode="create"
            selectedType={selectedType}
            channelTypes={channelTypes}
            loadingTypes={loadingTypes}
            loadingSchema={loadingSchema}
            saving={saving}
            settingsSchema={settingsSchema}
            settingsValues={settingsValues}
            isEnabled={isEnabled}
            submitDisabled={submitDisabled}
            onTypeChange={(value) => {
              setSelectedType(value);
              setSettingsValues({});
            }}
            onSettingsChange={setSettingsValues}
            onEnabledChange={setIsEnabled}
            onSubmit={() => void handleSave()}
            onCancel={closeEditor}
          />
        </div>
      )}

      <div className="space-y-3">
        {loadingBots ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            Загрузка ботов...
          </div>
        ) : bots.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-muted/20 px-5 py-10 text-center">
            <p className="font-medium">Каналы пока не настроены</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Создайте первый bot instance и заполните его настройки по схеме выбранного типа.
            </p>
          </div>
        ) : (
          bots.map((bot) => {
            const isDeleting = deletingBotId === bot.id;
            const isBusy = isCreatingNew || saving || isDeleting;

            if (editingBotId === bot.id) {
              return (
                <div
                  key={bot.id}
                  className="space-y-6 rounded-xl border border-border bg-muted/20 p-4"
                >
                  <div className="mb-4 flex items-center justify-between">
                    <div>
                      <h4 className="font-medium">
                        Редактирование: {formatChannelName(bot)}
                      </h4>
                      <p className="mt-1 text-sm text-muted-foreground">
                        Измените настройки выбранного бота и при необходимости обновите его контакты.
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={closeEditor}
                      disabled={saving}
                    >
                      <X className="size-4" />
                    </Button>
                  </div>

                  {loadingDialogData ? (
                    <div className="flex items-center justify-center py-8 text-muted-foreground">
                      <Loader2 className="mr-2 size-4 animate-spin" />
                      Загрузка данных бота...
                    </div>
                  ) : (
                    <>
                      <ChannelForm
                        mode="edit"
                        selectedType={selectedType}
                        channelTypes={channelTypes}
                        loadingTypes={loadingTypes}
                        loadingSchema={loadingSchema}
                        saving={saving}
                        settingsSchema={settingsSchema}
                        settingsValues={settingsValues}
                        isEnabled={isEnabled}
                        submitDisabled={submitDisabled}
                        onTypeChange={() => {
                          // Type is read-only in edit mode.
                        }}
                        onSettingsChange={setSettingsValues}
                        onEnabledChange={setIsEnabled}
                        onSubmit={() => void handleSave()}
                        onCancel={closeEditor}
                      />

                      <div className="space-y-3">
                        <div>
                          <h4 className="font-medium">Контакты</h4>
                          <p className="mt-1 text-sm text-muted-foreground">
                            Пользователи и чаты, которые уже взаимодействовали с этим ботом.
                          </p>
                        </div>
                        <ContactsSection
                          botId={bot.id}
                          contacts={contacts}
                          loading={loadingContacts}
                          actionKey={contactActionKey}
                          onApproveToggle={handleApproveToggle}
                          onDelete={handleDeleteContact}
                        />
                      </div>
                    </>
                  )}
                </div>
              );
            }

            return (
              <div
                key={bot.id}
                className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-card px-4 py-3 transition-colors hover:bg-accent/30"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{formatChannelName(bot)}</span>
                    <Badge variant="outline">{bot.channel_type}</Badge>
                    <Badge variant={bot.is_enabled ? "default" : "secondary"}>
                      {bot.is_enabled ? "Включен" : "Выключен"}
                    </Badge>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    ID: {bot.id}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void handleStartEdit(bot.id)}
                    disabled={isBusy}
                  >
                    <Pencil className="mr-2 size-4" />
                    Редактировать
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => void handleDeleteBot(bot.id)}
                    disabled={isBusy}
                    title="Удалить бота"
                  >
                    {isDeleting ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Trash2 className="size-4 text-destructive" />
                    )}
                  </Button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default ChannelsSettings;
