import React, { useMemo, useState } from "react";
import { Check, ExternalLink, Plus, Search, Settings2, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input, SecretInput } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api-client";
import { API_AGENT_PREFIX, RUNTIME_LOCAL } from "@/config.ts";
import { useUserInfo } from "@/components/providers/user-info";
import { useOAuthPopup } from "@/components/integrations/use-oauth-popup";
import type { AuthType, CatalogEntry, ModuleCatalogEntry } from "./types";
import type { UseConnectorsResult } from "./use-connectors";

const INTEGRATIONS_URL = `${API_AGENT_PREFIX}/integrations`;

// Нормализованная запись для единого грида (MCP-шаблон или модуль).
interface DisplayEntry {
  key: string;
  kind: "mcp" | "module";
  id: string;
  name: string;
  description?: string | null;
  icon?: string | null;
  homepage?: string | null;
  categories: string[];
  authLabel: string;
  fields: {
    key: string;
    label: string;
    secret?: boolean;
    placeholder?: string | null;
    help_url?: string | null;
  }[];
  connected: boolean;
  mcp?: CatalogEntry;
  module?: ModuleCatalogEntry;
}

interface DirectoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  api: UseConnectorsResult;
  onManage: () => void;
}

const ConnectorsDirectoryModal: React.FC<DirectoryModalProps> = ({
  isOpen,
  onClose,
  api,
  onManage,
}) => {
  const {
    catalog,
    moduleCatalog,
    connectors,
    connect,
    authorize,
    createCustom,
    reloadCatalog,
    remove,
  } = api;
  const { refreshModules } = useUserInfo();

  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [openFormId, setOpenFormId] = useState<string | null>(null);
  const [inputs, setInputs] = useState<Record<string, Record<string, string>>>(
    {},
  );
  const [connectingId, setConnectingId] = useState<string | null>(null);
  // Карточка, для которой открыт диалог подтверждения отключения.
  const [confirmDisconnect, setConfirmDisconnect] =
    useState<DisplayEntry | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);

  // Кастомный коннектор
  const [showCustom, setShowCustom] = useState(false);
  const [cName, setCName] = useState("");
  const [cUrl, setCUrl] = useState("");
  const [cAuth, setCAuth] = useState<AuthType>("none");
  const [cToken, setCToken] = useState("");
  const [cScope, setCScope] = useState("");
  const [creating, setCreating] = useState(false);

  const connectedUrls = useMemo(
    () => new Set(connectors.map((s) => s.url)),
    [connectors],
  );

  // Единый список карточек: MCP-шаблоны + подключаемые модули.
  const displays = useMemo<DisplayEntry[]>(() => {
    const mcpItems: DisplayEntry[] = catalog.map((e) => ({
      key: `mcp:${e.id}`,
      kind: "mcp",
      id: e.id,
      name: e.name,
      description: e.description,
      icon: e.icon,
      homepage: e.homepage,
      categories: e.categories ?? [],
      authLabel: String(e.auth_type),
      fields: e.requires ?? [],
      connected: connectedUrls.has(e.url),
      mcp: e,
    }));
    const moduleItems: DisplayEntry[] = moduleCatalog.map((m) => ({
      key: `module:${m.provider_key}`,
      kind: "module",
      id: m.module_id,
      name: m.name,
      description: m.description,
      icon: m.icon,
      categories: m.categories ?? [],
      authLabel: m.auth_kind === "oauth2" ? "oauth2" : "token",
      fields: m.manual_fields ?? [],
      connected: m.status === "connected",
      module: m,
    }));
    return [...moduleItems, ...mcpItems];
  }, [catalog, moduleCatalog, connectedUrls]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    displays.forEach((e) => e.categories.forEach((c) => set.add(c)));
    return Array.from(set).sort();
  }, [displays]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return displays.filter((e) => {
      if (category && !e.categories.includes(category)) return false;
      if (!q) return true;
      return (
        e.name.toLowerCase().includes(q) ||
        (e.description ?? "").toLowerCase().includes(q)
      );
    });
  }, [displays, query, category]);

  const openModuleOAuth = useOAuthPopup("integration_auth_callback", (success) => {
    if (success) {
      toast.success("Авторизация прошла успешно");
      void reloadCatalog();
      refreshModules();
    } else {
      toast.error("Авторизация не удалась");
    }
  });

  const handleConnectMcp = async (display: DisplayEntry) => {
    const entry = display.mcp!;
    const fields = entry.requires ?? [];
    if (fields.length > 0 && openFormId !== display.key) {
      setOpenFormId(display.key);
      return;
    }
    const entryInputs = inputs[display.key] ?? {};
    for (const f of fields) {
      if (!entryInputs[f.key]?.trim()) {
        toast.error(`Укажите: ${f.label}`);
        return;
      }
    }
    setConnectingId(display.key);
    try {
      const created = await connect(entry.id, entryInputs);
      setOpenFormId(null);
      setInputs((prev) => ({ ...prev, [display.key]: {} }));
      if (entry.auth_type === "oauth2" && created?.id) {
        toast.success(`${entry.name} добавлен — открываем авторизацию`);
        await authorize(created.id);
      } else {
        toast.success(`${entry.name} подключён`);
      }
    } catch (e: any) {
      toast.error(e?.message || "Не удалось подключить коннектор");
    } finally {
      setConnectingId(null);
    }
  };

  const handleConnectModule = async (display: DisplayEntry) => {
    const entry = display.module!;
    const fields = entry.manual_fields ?? [];
    // Модуль с токеном: первый клик — раскрыть форму.
    if (fields.length > 0 && openFormId !== display.key) {
      setOpenFormId(display.key);
      return;
    }
    setConnectingId(display.key);
    try {
      if (fields.length > 0) {
        const entryInputs = inputs[display.key] ?? {};
        for (const f of fields) {
          if (!entryInputs[f.key]?.trim()) {
            toast.error(`Укажите: ${f.label}`);
            return;
          }
        }
        await apiClient.post(
          `${INTEGRATIONS_URL}/${entry.provider_key}/token`,
          { fields: entryInputs },
        );
        setOpenFormId(null);
        setInputs((prev) => ({ ...prev, [display.key]: {} }));
        await reloadCatalog();
        refreshModules();
        toast.success(`${entry.name} подключён`);
      } else {
        const { authorization_url } = await apiClient.get<{
          authorization_url: string;
        }>(`${INTEGRATIONS_URL}/${entry.provider_key}/oauth/start`);
        openModuleOAuth(authorization_url);
      }
    } catch (e: any) {
      toast.error(e?.message || "Не удалось подключить модуль");
    } finally {
      setConnectingId(null);
    }
  };

  const handleConnect = (display: DisplayEntry) =>
    display.kind === "module"
      ? handleConnectModule(display)
      : handleConnectMcp(display);

  const handleDisconnect = async (display: DisplayEntry) => {
    setDisconnecting(true);
    try {
      if (display.kind === "module") {
        await apiClient.delete(
          `${INTEGRATIONS_URL}/${display.module!.provider_key}`,
        );
        await reloadCatalog();
        refreshModules();
      } else {
        // MCP-коннектор живёт в БД — находим по URL и удаляем.
        const server = connectors.find((s) => s.url === display.mcp!.url);
        if (server) await remove(server.id);
      }
      toast.success(`${display.name} отключён`);
    } catch (e: any) {
      toast.error(e?.message || "Не удалось отключить коннектор");
    } finally {
      setDisconnecting(false);
      setConfirmDisconnect(null);
    }
  };

  const handleCreateCustom = async () => {
    if (!cUrl.trim()) {
      toast.error("Укажите URL сервера");
      return;
    }
    setCreating(true);
    try {
      await createCustom({
        name: cName,
        url: cUrl,
        authType: cAuth,
        token: cToken,
        scope: cScope,
      });
      toast.success("Коннектор добавлен");
      setCName("");
      setCUrl("");
      setCToken("");
      setCScope("");
      setCAuth("none");
      setShowCustom(false);
    } catch (e: any) {
      toast.error(e?.message || "Не удалось добавить коннектор");
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
    <Dialog open={isOpen} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl max-h-[85vh] flex flex-col gap-4">
        <DialogHeader>
          <DialogTitle>Каталог коннекторов</DialogTitle>
          <DialogDescription>
            Подключите сервис из каталога или добавьте свой коннектор.
          </DialogDescription>
        </DialogHeader>

        {/* Поиск + быстрые действия */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
            <Input
              placeholder="Поиск коннекторов…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-8"
            />
          </div>
          <Button variant="outline" size="sm" onClick={onManage}>
            <Settings2 className="size-4 mr-1" />
            Управление
          </Button>
        </div>

        {/* Категории */}
        {categories.length > 0 && (
          <div className="flex flex-wrap gap-1">
            <Badge
              variant={category === null ? "default" : "outline"}
              className="cursor-pointer"
              onClick={() => setCategory(null)}
            >
              Все
            </Badge>
            {categories.map((c) => (
              <Badge
                key={c}
                variant={category === c ? "default" : "outline"}
                className="cursor-pointer"
                onClick={() => setCategory((prev) => (prev === c ? null : c))}
              >
                {c}
              </Badge>
            ))}
          </div>
        )}

        {/* Грид каталога */}
        <div className="overflow-y-auto flex-1 -mr-2 pr-2">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {filtered.length === 0 && (
              <div className="text-sm text-muted-foreground col-span-full py-6 text-center">
                Ничего не найдено
              </div>
            )}
            {filtered.map((entry) => {
              const connected = entry.connected;
              const fields = entry.fields;
              const formOpen = openFormId === entry.key;
              const busy = connectingId === entry.key;
              return (
                <div
                  key={entry.key}
                  className="rounded-md border bg-card p-3 flex flex-col gap-2 min-w-0"
                >
                  <div className="flex items-start gap-2">
                    {entry.icon && (
                      <img
                        src={entry.icon}
                        alt=""
                        className="h-6 w-6 rounded shrink-0 mt-0.5"
                        onError={(e) => {
                          e.currentTarget.style.display = "none";
                        }}
                      />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-sm flex items-center gap-1">
                        <span className="truncate">{entry.name}</span>
                        {entry.kind === "module" && (
                          <Badge
                            variant="secondary"
                            className="shrink-0 text-[10px] px-1 py-0"
                          >
                            модуль
                          </Badge>
                        )}
                        {entry.homepage && (
                          <a
                            href={entry.homepage}
                            target="_blank"
                            rel="noreferrer"
                            className="text-muted-foreground hover:text-foreground shrink-0"
                            title="Документация"
                          >
                            <ExternalLink size={12} />
                          </a>
                        )}
                      </div>
                      {entry.description && (
                        <div className="text-xs text-muted-foreground break-words [overflow-wrap:anywhere]">
                          {entry.description}
                        </div>
                      )}
                    </div>
                    <Badge variant="outline" className="shrink-0">
                      {entry.authLabel}
                    </Badge>
                  </div>

                  {formOpen &&
                    fields.map((f) => {
                      const InputComp = f.secret ? SecretInput : Input;
                      return (
                        <div key={f.key} className="space-y-1">
                          <InputComp
                            placeholder={f.placeholder || f.label}
                            value={inputs[entry.key]?.[f.key] ?? ""}
                            onChange={(e) =>
                              setInputs((prev) => ({
                                ...prev,
                                [entry.key]: {
                                  ...(prev[entry.key] ?? {}),
                                  [f.key]: e.target.value,
                                },
                              }))
                            }
                          />
                          {f.help_url && (
                            <a
                              href={f.help_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-xs text-primary underline"
                            >
                              Где взять {f.label}?
                            </a>
                          )}
                        </div>
                      );
                    })}

                  <div className="mt-auto flex items-center gap-2">
                    <Button
                      size="sm"
                      variant={connected ? "outline" : "default"}
                      disabled={connected || busy}
                      onClick={() => handleConnect(entry)}
                      className="w-fit"
                    >
                      {connected ? (
                        <>
                          <Check size={14} className="mr-1" />
                          Подключено
                        </>
                      ) : (
                        <>
                          <Plus size={14} className="mr-1" />
                          {fields.length > 0 && !formOpen
                            ? "Настроить"
                            : "Подключить"}
                        </>
                      )}
                    </Button>
                    {connected && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive ml-auto"
                        title="Отключить"
                        onClick={() => setConfirmDisconnect(entry)}
                      >
                        <Trash2 size={14} />
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Свой коннектор */}
        <div className="rounded-md border bg-muted/40 p-3 space-y-3">
          <button
            type="button"
            onClick={() => setShowCustom((v) => !v)}
            className="font-medium text-sm flex items-center gap-2 w-full text-left"
          >
            <Plus
              className={cn(
                "size-4 transition-transform",
                showCustom && "rotate-45",
              )}
            />
            Свой коннектор
          </button>
          {showCustom && (
            <div className="space-y-3">
              <Input
                placeholder="Название (необязательно)"
                value={cName}
                onChange={(e) => setCName(e.target.value)}
              />
              <Input
                placeholder="https://mcp.example.com/mcp"
                value={cUrl}
                onChange={(e) => setCUrl(e.target.value)}
              />
              <div className="flex items-center gap-2">
                {(["none", "bearer", "oauth2"] as AuthType[]).map((t) => (
                  <Badge
                    key={t}
                    variant={cAuth === t ? "default" : "outline"}
                    className="cursor-pointer"
                    onClick={() => setCAuth(t)}
                  >
                    {t}
                  </Badge>
                ))}
              </div>
              {cAuth === "bearer" && (
                <SecretInput
                  placeholder="Bearer-токен"
                  value={cToken}
                  onChange={(e) => setCToken(e.target.value)}
                />
              )}
              {cAuth === "oauth2" && (
                <Input
                  placeholder="OAuth scope (необязательно)"
                  value={cScope}
                  onChange={(e) => setCScope(e.target.value)}
                />
              )}
              <Button size="sm" onClick={handleCreateCustom} disabled={creating}>
                <Plus size={14} className="mr-1" />
                Добавить
              </Button>
            </div>
          )}
        </div>

        {RUNTIME_LOCAL && api.configPath && (
          <div className="text-xs text-muted-foreground">
            Локальные серверы настраиваются в {api.configPath} — см. «Управление».
          </div>
        )}
      </DialogContent>
    </Dialog>

    <AlertDialog
      open={confirmDisconnect !== null}
      onOpenChange={(o) => !o && !disconnecting && setConfirmDisconnect(null)}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Отключить коннектор?</AlertDialogTitle>
          <AlertDialogDescription>
            {confirmDisconnect
              ? `«${confirmDisconnect.name}» будет отключён, а его инструменты станут недоступны агенту.`
              : ""}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={disconnecting}>
            Отмена
          </AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-white hover:bg-destructive/90"
            disabled={disconnecting}
            onClick={(e) => {
              e.preventDefault();
              if (confirmDisconnect) void handleDisconnect(confirmDisconnect);
            }}
          >
            Отключить
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    </>
  );
};

export default ConnectorsDirectoryModal;
