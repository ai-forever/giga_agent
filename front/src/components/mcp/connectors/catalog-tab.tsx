import React, { useMemo, useRef, useState } from "react";
import {
  Check,
  ExternalLink,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api-client";
import { API_AGENT_PREFIX } from "@/config.ts";
import { useUserInfo } from "@/components/providers/user-info-context";
import { useOAuthPopup } from "@/components/integrations/use-oauth-popup";
import type {
  AuthType,
  CatalogEntry,
  ModuleCatalogEntry,
  UnifiedServer,
} from "./types";
import type { UseConnectorsResult } from "./use-connectors";

const INTEGRATIONS_URL = `${API_AGENT_PREFIX}/integrations`;

// Русские названия категорий каталога; неизвестные теги показываем как есть.
const CATEGORY_LABELS: Record<string, string> = {
  ai: "ИИ",
  code: "Разработка",
  crm: "CRM",
  dev: "Инструменты",
  diagrams: "Диаграммы",
  docs: "Документация",
  observability: "Мониторинг",
  retail: "Покупки",
  ru: "Российские",
  search: "Поиск",
  travel: "Путешествия",
  web: "Веб",
};

const categoryLabel = (c: string) => CATEGORY_LABELS[c] ?? c;

// Sentinel для «Все категории» — radix Select не принимает пустую строку.
const ALL_CATEGORIES = "__all__";

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
  needsAuth: boolean;
  mcp?: CatalogEntry;
  module?: ModuleCatalogEntry;
  // Подключённый db-сервер каталожного MCP (для авторизации/перехода).
  server?: UnifiedServer;
}

// id карточки на вкладке «Подключённые» — для автоперехода с подсветкой.
const highlightIdFor = (entry: DisplayEntry): string | null => {
  if (entry.kind === "module") return `module:${entry.module!.module_id}`;
  return entry.server && entry.server.source === "db"
    ? `db:${entry.server.id}`
    : null;
};

interface CatalogTabProps {
  api: UseConnectorsResult;
  // Переключиться на вкладку «Подключённые», подсветив карточку.
  onConnected: (highlightId: string | null) => void;
}

const ConnectorsCatalogTab: React.FC<CatalogTabProps> = ({
  api,
  onConnected,
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

  const connectorsByUrl = useMemo(() => {
    const map = new Map<string, UnifiedServer>();
    connectors.forEach((s) => {
      if (s.url) map.set(s.url, s);
    });
    return map;
  }, [connectors]);

  // Единый список карточек: MCP-шаблоны + подключаемые модули.
  const displays = useMemo<DisplayEntry[]>(() => {
    const mcpItems: DisplayEntry[] = catalog.map((e) => {
      const server = connectorsByUrl.get(e.url);
      return {
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
        connected: Boolean(server),
        needsAuth: Boolean(
          server &&
            server.source === "db" &&
            server.auth_type === "oauth2" &&
            !server.has_token,
        ),
        mcp: e,
        server,
      };
    });
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
      connected: m.status !== "not_connected",
      needsAuth: m.status === "needs_reauth",
      module: m,
    }));
    return [...moduleItems, ...mcpItems];
  }, [catalog, moduleCatalog, connectorsByUrl]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    displays.forEach((e) => e.categories.forEach((c) => set.add(c)));
    return Array.from(set).sort((a, b) =>
      categoryLabel(a).localeCompare(categoryLabel(b), "ru"),
    );
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

  // module_id модуля, для которого сейчас идёт OAuth в popup'е.
  const pendingModuleRef = useRef<string | null>(null);
  const openModuleOAuth = useOAuthPopup(
    "integration_auth_callback",
    (success) => {
      pendingModuleRef.current = null;
      if (success) {
        toast.success("Авторизация прошла успешно");
        void reloadCatalog();
        refreshModules();
        // Остаёмся на вкладке «Каталог» — карточка обновится сама после reload.
      } else {
        toast.error("Авторизация не удалась");
      }
    },
  );

  const startModuleOAuth = async (entry: ModuleCatalogEntry) => {
    const { authorization_url } = await apiClient.get<{
      authorization_url: string;
    }>(`${INTEGRATIONS_URL}/${entry.provider_key}/oauth/start`);
    pendingModuleRef.current = entry.module_id;
    openModuleOAuth(authorization_url);
  };

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
      // Остаёмся в каталоге — карточка сама отметится «Подключено» после reload.
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
        // Остаёмся в каталоге — карточка сама отметится «Подключено».
      } else {
        await startModuleOAuth(entry);
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

  // Дозавершить авторизацию уже подключённого коннектора (oauth2 без токена).
  const handleAuthorize = async (display: DisplayEntry) => {
    setConnectingId(display.key);
    try {
      if (display.kind === "module") {
        await startModuleOAuth(display.module!);
      } else if (display.server) {
        await authorize(display.server.id);
        onConnected(highlightIdFor(display));
      }
    } catch (e: any) {
      toast.error(e?.message || "Не удалось начать авторизацию");
    } finally {
      setConnectingId(null);
    }
  };

  const handleDisconnect = async (display: DisplayEntry) => {
    setDisconnecting(true);
    try {
      if (display.kind === "module") {
        await apiClient.delete(
          `${INTEGRATIONS_URL}/${display.module!.provider_key}`,
        );
        await reloadCatalog();
        refreshModules();
      } else if (display.server) {
        await remove(display.server.id);
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
    if (!cName.trim()) {
      toast.error("Укажите название коннектора");
      return;
    }
    if (!cUrl.trim()) {
      toast.error("Укажите URL сервера");
      return;
    }
    setCreating(true);
    try {
      const created = await createCustom({
        name: cName,
        url: cUrl,
        authType: cAuth,
        token: cToken,
        scope: cScope,
      });
      if (cAuth === "oauth2" && created?.id) {
        toast.success("Коннектор добавлен — открываем авторизацию");
        await authorize(created.id);
      } else {
        toast.success("Коннектор добавлен");
      }
      setCName("");
      setCUrl("");
      setCToken("");
      setCScope("");
      setCAuth("none");
      setShowCustom(false);
      onConnected(created?.id ? `db:${created.id}` : null);
    } catch (e: any) {
      toast.error(e?.message || "Не удалось добавить коннектор");
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      {/* Поиск + категория + свой коннектор */}
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
        {categories.length > 0 && (
          <Select
            value={category ?? ALL_CATEGORIES}
            onValueChange={(v) => setCategory(v === ALL_CATEGORIES ? null : v)}
          >
            <SelectTrigger className="shrink-0 max-w-[180px]">
              <SelectValue placeholder="Категория" />
            </SelectTrigger>
            <SelectContent className="z-1000">
              <SelectItem value={ALL_CATEGORIES}>Категории</SelectItem>
              {categories.map((c) => (
                <SelectItem key={c} value={c}>
                  {categoryLabel(c)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <Button
          variant={showCustom ? "secondary" : "outline"}
          size="sm"
          onClick={() => setShowCustom((v) => !v)}
        >
          <Plus
            className={cn(
              "size-4 mr-1 transition-transform",
              showCustom && "rotate-45",
            )}
          />
          Свой коннектор
        </Button>
      </div>

      {/* Форма своего коннектора */}
      {showCustom && (
        <div className="rounded-md border bg-muted/40 p-3 space-y-3">
          <Input
            placeholder="Название"
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
          <Button
            size="sm"
            onClick={handleCreateCustom}
            disabled={creating || !cName.trim() || !cUrl.trim()}
          >
            <Plus size={14} className="mr-1" />
            Добавить
          </Button>
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
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    {entry.needsAuth && (
                      <Badge
                        variant="outline"
                        className="border-amber-500/40 text-amber-500"
                      >
                        нужна авторизация
                      </Badge>
                    )}
                  </div>
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
                  {connected ? (
                    entry.needsAuth ? (
                      <Button
                        size="sm"
                        disabled={busy}
                        onClick={() => handleAuthorize(entry)}
                        className="w-fit"
                      >
                        <ShieldCheck size={14} className="mr-1" />
                        Авторизоваться
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        title="Перейти к управлению"
                        onClick={() => onConnected(highlightIdFor(entry))}
                        className="w-fit"
                      >
                        <Check size={14} className="mr-1" />
                        Подключено
                      </Button>
                    )
                  ) : (
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() => handleConnect(entry)}
                      className="w-fit"
                    >
                      <Plus size={14} className="mr-1" />
                      {fields.length > 0 && !formOpen
                        ? "Настроить"
                        : "Подключить"}
                    </Button>
                  )}
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

export default ConnectorsCatalogTab;
