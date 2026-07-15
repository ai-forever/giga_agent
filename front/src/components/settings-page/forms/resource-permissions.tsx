import React, { useEffect, useMemo, useState } from "react";

import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Loader2 } from "lucide-react";

import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { Label } from "@/components/ui/label";
import { SearchableMultiSelect } from "@/components/ui/searchable-select";
import { Switch } from "@/components/ui/switch";
import type { PermissionResourceType, ResourcePermissionsDraft } from "./types";

type UserOption = {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
};

type GroupOption = {
  id: string;
  name: string;
  description: string | null;
  // Маркер системной группы (data.system === "all_members" → вся команда).
  data?: { system?: string } | null;
};

interface ResourcePermissionsProps {
  mode: "create" | "edit";
  resourceType: PermissionResourceType;
  resourceId?: string;
  value: ResourcePermissionsDraft;
  onChange: (next: ResourcePermissionsDraft) => void;
  canManage: boolean;
  disabled?: boolean;
  defaultOpen?: boolean;
}

const ResourcePermissions: React.FC<ResourcePermissionsProps> = ({
  mode,
  resourceType,
  resourceId,
  value,
  onChange,
  canManage,
  disabled = false,
  defaultOpen = false,
}) => {
  const [users, setUsers] = useState<UserOption[]>([]);
  const [groups, setGroups] = useState<GroupOption[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [loadingGroups, setLoadingGroups] = useState(false);
  const [isOpen, setIsOpen] = useState(defaultOpen);

  useEffect(() => {
    if (!canManage) return;

    let cancelled = false;
    setLoadingUsers(true);
    setLoadingGroups(true);

    const run = async () => {
      try {
        const [usersData, groupsData] = await Promise.all([
          apiClient.get<UserOption[]>(`${API_AGENT_PREFIX}/auth/users`),
          apiClient.get<GroupOption[]>(`${API_AGENT_PREFIX}/groups`),
        ]);
        if (cancelled) return;
        setUsers(usersData);
        setGroups(groupsData);
      } catch {
        if (cancelled) return;
        setUsers([]);
        setGroups([]);
      } finally {
        if (!cancelled) {
          setLoadingUsers(false);
          setLoadingGroups(false);
        }
      }
    };

    void run();

    return () => {
      cancelled = true;
    };
  }, [canManage]);

  const userOptions = useMemo(
    () =>
      users.map((user) => {
        const fullName =
          `${user.first_name ?? ""} ${user.last_name ?? ""}`.trim();
        return {
          value: user.id,
          label: fullName ? `${user.email} (${fullName})` : user.email,
        };
      }),
    [users],
  );

  const groupOptions = useMemo(
    () =>
      groups.map((group) => ({
        value: group.id,
        label: group.description
          ? `${group.name} (${group.description})`
          : group.name,
      })),
    [groups],
  );

  const allMembersId = useMemo(
    () => groups.find((g) => g.data?.system === "all_members")?.id ?? null,
    [groups],
  );
  const sharedWithTeam = Boolean(
    allMembersId && value.read_group_ids.includes(allMembersId),
  );

  if (!canManage) {
    return null;
  }

  const isLoading = loadingUsers || loadingGroups;
  const isDisabled = disabled || isLoading;
  const targetLabel =
    mode === "edit" && resourceId
      ? `${resourceType}:${resourceId.slice(0, 8)}`
      : `${resourceType}:new`;

  const toggleTeamShare = (checked: boolean) => {
    if (!allMembersId) return;
    const rest = value.read_group_ids.filter((id) => id !== allMembersId);
    onChange({
      ...value,
      read_group_ids: checked ? [...rest, allMembersId] : rest,
    });
  };

  return (
    <div className="space-y-3">
      {/* Быстрый шаринг на всю команду — виден без разворачивания секции */}
      {allMembersId && (
        <div className="flex items-center justify-between rounded-md border border-border p-3">
          <div>
            <Label htmlFor="permission-team-share" className="cursor-pointer">
              Доступно команде
            </Label>
            <p className="text-xs text-muted-foreground mt-0.5">
              Все участники получат доступ на чтение
            </p>
          </div>
          <Switch
            id="permission-team-share"
            checked={sharedWithTeam}
            onCheckedChange={toggleTeamShare}
            disabled={isDisabled}
          />
        </div>
      )}
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className="flex items-center gap-2 w-full py-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <div className="flex-1 h-px bg-border" />
        <span className="flex items-center gap-1.5">
          Настроить права доступа
          <ChevronDown
            className={`size-4 transition-transform ${isOpen ? "rotate-180" : ""}`}
          />
        </span>
        <div className="flex-1 h-px bg-border" />
      </button>

      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="space-y-4 rounded-md border border-border p-4">
              <div>
                <h4 className="text-sm font-medium">Права доступа</h4>
                <p className="text-xs text-muted-foreground mt-1">
                  Ресурс: {targetLabel}
                </p>
              </div>

              {isLoading && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Загрузка пользователей и групп...
                </div>
              )}

              <div className="space-y-1.5">
                <Label>Пользователи (read)</Label>
                <SearchableMultiSelect
                  options={userOptions}
                  values={value.read_user_ids}
                  onValuesChange={(nextValues) =>
                    onChange({ ...value, read_user_ids: nextValues })
                  }
                  placeholder="Выберите пользователей"
                  searchPlaceholder="Поиск пользователя..."
                  emptyText="Пользователи не найдены"
                  disabled={isDisabled}
                />
              </div>

              <div className="space-y-1.5">
                <Label>Группы (read)</Label>
                <SearchableMultiSelect
                  options={groupOptions}
                  values={value.read_group_ids}
                  onValuesChange={(nextValues) =>
                    onChange({ ...value, read_group_ids: nextValues })
                  }
                  placeholder="Выберите группы"
                  searchPlaceholder="Поиск группы..."
                  emptyText="Группы не найдены"
                  disabled={isDisabled}
                />
              </div>

              <div className="flex items-center justify-between rounded-md border border-border p-3">
                <Label
                  htmlFor="permission-public-read"
                  className="cursor-pointer"
                >
                  Публичный доступ на чтение
                </Label>
                <Switch
                  id="permission-public-read"
                  checked={value.public_read}
                  onCheckedChange={(checked) =>
                    onChange({ ...value, public_read: checked })
                  }
                  disabled={isDisabled}
                />
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ResourcePermissions;
