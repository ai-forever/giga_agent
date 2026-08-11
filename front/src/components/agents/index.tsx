import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bot,
  CheckCircle2,
  Copy,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { API_AGENT_PREFIX } from "@/config";
import { apiClient } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  SearchableMultiSelect,
  SearchableSelect,
} from "@/components/ui/searchable-select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import ConnectorIcon from "@/components/mcp/connectors/connector-icon";
import { iconForConnector } from "@/components/mcp/connectors/types";
import { useConfirm } from "@/components/providers/confirm";
import { useUserInfo } from "@/components/providers/user-info-context";
import {
  AgentDefinition,
  AgentDraft,
  AgentEditorOptions,
  cloneAgent,
  createAgent,
  deleteAgent,
  getAgentEditorOptions,
  installAgentSkills,
  listAgents,
  setAgentEnabled,
  ToolEffect,
  updateAgent,
  updateAgentBindings,
} from "./api";

type McpServer = {
  id: string;
  name?: string;
  catalog_id?: string | null;
  is_active: boolean;
};
type Skill = { id: string; name: string; is_enabled: boolean };
type Llm = { id: string; name?: string; model_id: string; is_active: boolean };
type AgentFilter = "all" | "builtin" | "custom";

const emptyDraft: AgentDraft = {
  name: "",
  description: "",
  prompt: "",
  modules: [],
  mcp_server_ids: [],
  skill_names: [],
  allowed_tool_effects: ["read"],
  llm_id: null,
  is_enabled: true,
};

const effectLabels: Record<ToolEffect, string> = {
  read: "Чтение",
  write: "Редактирование",
  destructive: "Деструктивные тулы",
};

const draftFromAgent = (agent: AgentDefinition): AgentDraft => ({
  name: agent.name,
  description: agent.description,
  prompt: agent.prompt,
  modules: agent.modules,
  mcp_server_ids: agent.mcp_server_ids ?? [],
  skill_names:
    agent.skill_names ?? (agent.skills ?? []).map((item) => item.name),
  allowed_tool_effects: agent.allowed_tool_effects ?? ["read"],
  llm_id: agent.llm_id ?? null,
  is_enabled: agent.enabled,
});

const AgentEditorPanel: React.FC<{
  agent: AgentDefinition | null;
  onClose: () => void;
  onSaved: (agent: AgentDefinition) => void;
}> = ({ agent, onClose, onSaved }) => {
  const { connectors: connectorApi } = useUserInfo();
  const [draft, setDraft] = useState<AgentDraft>(() =>
    agent ? draftFromAgent(agent) : emptyDraft,
  );
  const [options, setOptions] = useState<AgentEditorOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setDraft(agent ? draftFromAgent(agent) : emptyDraft);
    void getAgentEditorOptions()
      .then((value) => {
        if (!cancelled) {
          setOptions(value);
          if (!agent) {
            setDraft((current) => ({
              ...current,
              modules: value.modules.map((item) => item.id),
            }));
          }
        }
      })
      .catch(() => {
        if (!cancelled) toast.error("Не удалось загрузить доступные ресурсы");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agent]);

  const setField = <K extends keyof AgentDraft>(
    field: K,
    value: AgentDraft[K],
  ) => setDraft((current) => ({ ...current, [field]: value }));

  const toggleEffect = (effect: ToolEffect) => {
    setDraft((current) => {
      const selected = new Set(current.allowed_tool_effects);
      if (selected.has(effect)) selected.delete(effect);
      else selected.add(effect);
      return {
        ...current,
        allowed_tool_effects: (
          ["read", "write", "destructive"] as ToolEffect[]
        ).filter((item) => selected.has(item)),
      };
    });
  };

  const save = async () => {
    if (
      !draft.name.trim() ||
      !draft.description.trim() ||
      !draft.prompt.trim()
    ) {
      toast.error("Заполните название, описание и prompt");
      return;
    }
    setSaving(true);
    try {
      const saved = agent
        ? await updateAgent(agent.ref, draft)
        : await createAgent(draft);
      toast.success(agent ? "Агент обновлён" : "Суб-агент создан");
      onSaved(saved);
    } catch {
      toast.error("Не удалось сохранить суб-агента");
    } finally {
      setSaving(false);
    }
  };

  const moduleOptions = (options?.modules ?? []).map((item) => ({
    value: item.id,
    label: item.label,
  }));
  const mcpOptions = (options?.mcp_servers ?? []).map((item) => ({
    value: item.id,
    label: item.name,
    icon: (
      <ConnectorIcon
        src={(() => {
          const server = connectorApi.connectors.find(
            (value) => value.id === item.id,
          );
          return server ? iconForConnector(server, connectorApi.catalog) : null;
        })()}
        className="size-4"
      />
    ),
  }));
  const skillOptions = (options?.skills ?? []).map((item) => ({
    value: item.name,
    label: item.name,
  }));
  const llmOptions = [
    { value: "__inherit__", label: "Как у основного агента" },
    ...(options?.llms ?? []).map((item) => ({
      value: item.id,
      label: `${item.name} (${item.model_id})`,
    })),
  ];

  return (
    <section className="flex h-full min-h-0 flex-col overflow-y-auto overscroll-contain border-l border-border bg-card">
      <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-border bg-card px-6 py-4">
        <div>
          <h2 className="text-lg font-semibold">
            {agent ? "Редактирование суб-агента" : "Новый суб-агент"}
          </h2>
          <p className="text-xs text-muted-foreground">
            Настройте возможности, которые будут доступны агенту.
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label="Закрыть редактор"
        >
          <X className="size-4" />
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="size-6 animate-spin" />
        </div>
      ) : (
        <div className="grid gap-5 p-6">
          <>
            <div className="grid gap-2">
              <Label htmlFor="agent-name">Название</Label>
              <Input
                id="agent-name"
                value={draft.name}
                onChange={(e) => setField("name", e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="agent-description">Описание</Label>
              <Input
                id="agent-description"
                value={draft.description}
                onChange={(e) => setField("description", e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="agent-prompt">Промпт</Label>
              <Textarea
                id="agent-prompt"
                className="min-h-48 font-mono"
                value={draft.prompt}
                onChange={(e) => setField("prompt", e.target.value)}
              />
            </div>
          </>

          <>
            <div className="grid gap-2">
              <div className="flex items-center justify-between gap-2">
                <Label>Модули основного агента</Label>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  disabled={moduleOptions.length === 0}
                  onClick={() =>
                    setField(
                      "modules",
                      draft.modules.length === moduleOptions.length
                        ? []
                        : moduleOptions.map((option) => option.value),
                    )
                  }
                >
                  {draft.modules.length === moduleOptions.length
                    ? "Очистить выбор"
                    : "Выбрать все"}
                </Button>
              </div>
              <SearchableMultiSelect
                options={moduleOptions}
                values={draft.modules}
                onValuesChange={(value) => setField("modules", value)}
                placeholder="Выберите модули"
                searchPlaceholder="Найти модуль..."
              />
            </div>
            <div className="grid gap-2">
              <div className="flex items-center justify-between gap-2">
                <Label>MCP-серверы</Label>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  disabled={mcpOptions.length === 0}
                  onClick={() =>
                    setField(
                      "mcp_server_ids",
                      draft.mcp_server_ids.length === mcpOptions.length
                        ? []
                        : mcpOptions.map((option) => option.value),
                    )
                  }
                >
                  {draft.mcp_server_ids.length === mcpOptions.length
                    ? "Очистить выбор"
                    : "Выбрать все"}
                </Button>
              </div>
              <SearchableMultiSelect
                options={mcpOptions}
                values={draft.mcp_server_ids}
                onValuesChange={(value) => setField("mcp_server_ids", value)}
                placeholder="Выберите MCP-серверы"
                searchPlaceholder="Найти сервер..."
              />
            </div>
            <div className="grid gap-2">
              <div className="flex items-center justify-between gap-2">
                <Label>Навыки</Label>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  disabled={skillOptions.length === 0}
                  onClick={() =>
                    setField(
                      "skill_names",
                      draft.skill_names.length === skillOptions.length
                        ? []
                        : skillOptions.map((option) => option.value),
                    )
                  }
                >
                  {draft.skill_names.length === skillOptions.length
                    ? "Очистить выбор"
                    : "Выбрать все"}
                </Button>
              </div>
              <SearchableMultiSelect
                options={skillOptions}
                values={draft.skill_names}
                onValuesChange={(value) => setField("skill_names", value)}
                placeholder="Навыки"
                searchPlaceholder="Найти skill..."
              />
            </div>
          </>

          <>
            <div className="grid gap-2">
              <Label>LLM</Label>
              <SearchableSelect
                options={llmOptions}
                value={draft.llm_id ?? "__inherit__"}
                onValueChange={(value) =>
                  setField("llm_id", value === "__inherit__" ? null : value)
                }
                placeholder="Выберите LLM"
                searchPlaceholder="Найти LLM..."
              />
            </div>
          </>

          <>
            <div className="grid gap-2">
              <Label>Доступные инструменты</Label>
              <div
                className="flex flex-wrap gap-2"
                role="group"
                aria-label="Доступные инструменты"
              >
                {(["read", "write", "destructive"] as ToolEffect[]).map(
                  (effect) => {
                    const selected =
                      draft.allowed_tool_effects.includes(effect);
                    return (
                      <button
                        key={effect}
                        type="button"
                        aria-pressed={selected}
                        onClick={() => toggleEffect(effect)}
                        className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <Badge variant={selected ? "default" : "outline"}>
                          {effectLabels[effect]}
                        </Badge>
                      </button>
                    );
                  },
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Реальные инструменты дополнительно проверяются backend по их
                safety-классу.
              </p>
            </div>
            <div className="flex items-center justify-between rounded-md border border-border p-3">
              <div>
                <Label htmlFor="agent-enabled">Активен</Label>
                <p className="text-xs text-muted-foreground">
                  Разрешить основному агенту делегировать задачи.
                </p>
              </div>
              <Switch
                id="agent-enabled"
                checked={draft.is_enabled}
                onCheckedChange={(value) => setField("is_enabled", value)}
              />
            </div>
          </>

          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <Button variant="outline" onClick={onClose}>
              Отмена
            </Button>
            <Button onClick={() => void save()} disabled={saving}>
              {saving && <Loader2 className="mr-2 size-4 animate-spin" />}
              Сохранить
            </Button>
          </div>
        </div>
      )}
    </section>
  );
};

const AgentsPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const confirm = useConfirm();
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [agentFilter, setAgentFilter] = useState<AgentFilter>("all");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setAgents(await listAgents());
    } catch {
      toast.error("Не удалось загрузить суб-агентов");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => void reload(), [reload]);

  const editorRef = useMemo(() => {
    const match = location.pathname.match(/\/agents\/(new|.+)\/edit$/);
    if (match) return decodeURIComponent(match[1]);
    return location.pathname.endsWith("/agents/new") ? "new" : null;
  }, [location.pathname]);
  const editingAgent =
    editorRef && editorRef !== "new"
      ? (agents.find((item) => item.ref === editorRef) ?? null)
      : null;

  const run = async (
    key: string,
    action: () => Promise<unknown>,
    message: string,
  ) => {
    setBusy(key);
    try {
      await action();
      toast.success(message);
      await reload();
    } catch {
      toast.error("Операция не выполнена");
    } finally {
      setBusy(null);
    }
  };

  const removeAgent = async (item: AgentDefinition) => {
    const confirmed = await confirm({
      title: "Удалить суб-агента?",
      description: `Суб-агент «${item.name}» будет удалён без возможности восстановления.`,
      confirmText: "Удалить",
      cancelText: "Отмена",
      variant: "destructive",
    });
    if (!confirmed) return;
    await run(item.ref, () => deleteAgent(item.ref), "Агент удалён");
  };

  const setup = async (item: AgentDefinition) => {
    setBusy(item.ref);
    try {
      if ((item.skills ?? []).some((skill) => skill.source))
        await installAgentSkills(item.ref);
      const [servers, skills, llms] = await Promise.all([
        apiClient.get<McpServer[]>(`${API_AGENT_PREFIX}/mcp/servers`),
        apiClient.get<Skill[]>(`${API_AGENT_PREFIX}/skills/`),
        apiClient.get<Llm[]>(`${API_AGENT_PREFIX}/llms`),
      ]);
      const skillBindings: Record<string, string> = {};
      for (const requirement of item.skills ?? []) {
        const skill = skills.find(
          (value) => value.name === requirement.name && value.is_enabled,
        );
        if (skill) skillBindings[requirement.name] = skill.id;
      }
      const connectorBindings: Record<string, string> = {};
      for (const catalogId of item.connectors ?? []) {
        const matches = servers.filter(
          (server) => server.catalog_id === catalogId && server.is_active,
        );
        if (matches.length === 1) connectorBindings[catalogId] = matches[0].id;
      }
      const inheritedLlm =
        item.llm_id ?? llms.find((llm) => llm.is_active)?.id ?? null;
      await updateAgentBindings(item.ref, {
        llm_id: item.source === "custom" ? inheritedLlm : null,
        skills: skillBindings,
        connectors: connectorBindings,
      });
      toast.success("Зависимости агента проверены и привязаны");
      await reload();
    } catch {
      toast.error("Не удалось настроить встроенный агент");
    } finally {
      setBusy(null);
    }
  };

  const visibleAgents = useMemo(
    () =>
      agents.filter(
        (item) => agentFilter === "all" || item.source === agentFilter,
      ),
    [agentFilter, agents],
  );

  return (
    <main className="relative flex min-h-0 w-full flex-1 flex-col overflow-hidden bg-card min-[901px]:flex-row">
      <section
        className={`min-h-0 min-w-0 flex-1 overflow-y-auto p-6 md:p-10 ${
          editorRef ? "min-[901px]:w-1/2 min-[901px]:flex-none" : ""
        }`}
      >
        <div className="mx-auto w-full max-w-5xl">
          <div className="mb-8 flex items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold">Суб-агенты</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Изолированные исполнители стандартного графа GigaAgent.
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="icon"
                onClick={() => void reload()}
                aria-label="Обновить список"
              >
                <RefreshCw className="size-4" />
              </Button>
              <Button onClick={() => navigate("/agents/new")}>
                <Plus className="mr-2 size-4" />
                Создать
              </Button>
            </div>
          </div>
          {loading ? (
            <div className="flex justify-center py-20">
              <Loader2 className="size-6 animate-spin" />
            </div>
          ) : (
            <div className="grid gap-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-1 rounded-lg border border-border p-1">
                  {(
                    [
                      ["all", "Все", agents.length],
                      [
                        "builtin",
                        "Встроенные",
                        agents.filter((item) => item.source === "builtin")
                          .length,
                      ],
                      [
                        "custom",
                        "Мои",
                        agents.filter((item) => item.source === "custom")
                          .length,
                      ],
                    ] as [AgentFilter, string, number][]
                  ).map(([value, label, count]) => (
                    <Button
                      key={value}
                      type="button"
                      size="sm"
                      variant={agentFilter === value ? "secondary" : "ghost"}
                      className="h-7 px-2 text-xs"
                      onClick={() => setAgentFilter(value)}
                    >
                      {label} · {count}
                    </Button>
                  ))}
                </div>
                <span className="text-xs text-muted-foreground">
                  {visibleAgents.length} из {agents.length}
                </span>
              </div>

              {visibleAgents.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
                  В этой категории пока нет суб-агентов
                </div>
              ) : (
                <div className="divide-y divide-border overflow-hidden rounded-lg border border-border">
                  {visibleAgents.map((item) => (
                    <div
                      key={item.ref}
                      className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center"
                    >
                      <div className="flex min-w-0 flex-1 items-start gap-3">
                        <Bot className="mt-0.5 size-4 shrink-0" />
                        <div className="min-w-0 flex-1">
                          <div className="flex min-w-0 items-center gap-2">
                            <h2 className="truncate text-sm font-medium">
                              {item.name}
                            </h2>
                            <span className="shrink-0 text-xs text-muted-foreground">
                              {item.source === "builtin"
                                ? "Встроенный"
                                : "Мой агент"}
                            </span>
                          </div>
                          <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                            {item.description}
                          </p>
                          {item.missing.length > 0 && (
                            <p className="mt-1 text-xs text-amber-600">
                              Не хватает:{" "}
                              {item.missing
                                .map((value) => `${value.kind}:${value.id}`)
                                .join(", ")}
                            </p>
                          )}
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-2 sm:shrink-0">
                        {item.readiness === "ready" ? (
                          <span
                            className="inline-flex text-emerald-600"
                            title="Готов"
                            aria-label="Готов"
                          >
                            <CheckCircle2 className="size-4" />
                          </span>
                        ) : (
                          <span className="text-xs text-amber-600">
                            Нужна настройка
                          </span>
                        )}
                        <Switch
                          checked={item.enabled}
                          disabled={busy === item.ref}
                          aria-label={`${item.enabled ? "Выключить" : "Включить"} ${item.name}`}
                          onCheckedChange={(enabled) =>
                            void run(
                              item.ref,
                              () => setAgentEnabled(item.ref, enabled),
                              enabled ? "Агент включён" : "Агент выключен",
                            )
                          }
                        />
                        {item.readiness !== "ready" &&
                          item.source === "builtin" && (
                            <Button
                              size="sm"
                              onClick={() => void setup(item)}
                              disabled={busy === item.ref}
                            >
                              {busy === item.ref && (
                                <Loader2 className="mr-2 size-4 animate-spin" />
                              )}
                              Настроить
                            </Button>
                          )}
                        {item.source === "builtin" ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              void cloneAgent(item.ref)
                                .then((created) => {
                                  toast.success("Создан custom-суб-агент");
                                  setAgents((current) => [...current, created]);
                                  navigate(
                                    `/agents/${encodeURIComponent(created.ref)}/edit`,
                                  );
                                })
                                .catch(() =>
                                  toast.error("Не удалось клонировать агента"),
                                )
                            }
                          >
                            <Copy className="mr-2 size-4" />
                            Клонировать
                          </Button>
                        ) : (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                navigate(
                                  `/agents/${encodeURIComponent(item.ref)}/edit`,
                                )
                              }
                            >
                              Редактировать
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              aria-label="Удалить суб-агента"
                              title="Удалить"
                              onClick={() => void removeAgent(item)}
                            >
                              <Trash2 className="size-4 text-destructive" />
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </section>
      {editorRef && (editorRef === "new" || editingAgent) && (
        <div className="absolute inset-0 z-20 h-full min-h-0 w-full overflow-hidden border-l border-border bg-card shadow-xl animate-in fade-in slide-in-from-right-4 duration-300 ease-out motion-reduce:animate-none min-[901px]:static min-[901px]:inset-auto min-[901px]:w-1/2 min-[901px]:shrink-0">
          <AgentEditorPanel
            agent={editingAgent}
            onClose={() => navigate("/agents")}
            onSaved={(saved) => {
              setAgents((current) => {
                const index = current.findIndex(
                  (item) => item.ref === saved.ref,
                );
                if (index === -1) return [...current, saved];
                const next = [...current];
                next[index] = saved;
                return next;
              });
              navigate("/agents");
            }}
          />
        </div>
      )}
    </main>
  );
};

export default AgentsPage;
