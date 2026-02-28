import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, Loader2, Pencil, Plus, Trash2, UserPlus } from "lucide-react";
import { toast } from "sonner";

import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SearchableMultiSelect } from "@/components/ui/searchable-select";
import { Textarea } from "@/components/ui/textarea";
import type { AdminGroup, AdminUser, GroupMember } from "./types";

type GroupFormState = {
  name: string;
  description: string;
};

const initialFormState: GroupFormState = {
  name: "",
  description: "",
};

const AdminGroupsTab: React.FC = () => {
  const [groups, setGroups] = useState<AdminGroup[]>([]);
  const [allUsers, setAllUsers] = useState<AdminUser[]>([]);
  const [membersByGroupId, setMembersByGroupId] = useState<
    Record<string, GroupMember[]>
  >({});
  const [selectedUserIdsByGroupId, setSelectedUserIdsByGroupId] = useState<
    Record<string, string[]>
  >({});
  const [expandedGroupId, setExpandedGroupId] = useState<string | null>(null);

  const [loadingGroups, setLoadingGroups] = useState(false);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [loadingMembersFor, setLoadingMembersFor] = useState<string | null>(
    null,
  );
  const [creating, setCreating] = useState(false);
  const [deletingGroupId, setDeletingGroupId] = useState<string | null>(null);
  const [addingMemberFor, setAddingMemberFor] = useState<string | null>(null);
  const [removingMemberKey, setRemovingMemberKey] = useState<string | null>(
    null,
  );
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null);
  const [updatingGroup, setUpdatingGroup] = useState(false);

  const [search, setSearch] = useState("");
  const [form, setForm] = useState<GroupFormState>(initialFormState);
  const [editForm, setEditForm] = useState<GroupFormState>(initialFormState);

  const fetchGroups = useCallback(async () => {
    setLoadingGroups(true);
    try {
      const data = await apiClient.get<AdminGroup[]>(
        `${API_AGENT_PREFIX}/groups`,
      );
      setGroups(data);
    } finally {
      setLoadingGroups(false);
    }
  }, []);

  const fetchUsers = useCallback(async () => {
    setLoadingUsers(true);
    try {
      const data = await apiClient.get<AdminUser[]>(
        `${API_AGENT_PREFIX}/auth/users`,
      );
      setAllUsers(data);
    } finally {
      setLoadingUsers(false);
    }
  }, []);

  useEffect(() => {
    void Promise.all([fetchGroups(), fetchUsers()]);
  }, [fetchGroups, fetchUsers]);

  const fetchGroupMembers = useCallback(async (groupId: string) => {
    setLoadingMembersFor(groupId);
    try {
      const data = await apiClient.get<GroupMember[]>(
        `${API_AGENT_PREFIX}/groups/${groupId}/users`,
      );
      setMembersByGroupId((prev) => ({ ...prev, [groupId]: data }));
    } finally {
      setLoadingMembersFor(null);
    }
  }, []);

  const filteredGroups = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return groups;

    return groups.filter((g) => {
      return (
        g.name.toLowerCase().includes(q) ||
        (g.description ?? "").toLowerCase().includes(q)
      );
    });
  }, [groups, search]);

  const handleCreateGroup = async (e: React.FormEvent) => {
    e.preventDefault();

    setCreating(true);
    try {
      await apiClient.post(`${API_AGENT_PREFIX}/groups`, {
        name: form.name,
        description: form.description || null,
      });
      toast.success("Группа создана");
      setForm(initialFormState);
      await fetchGroups();
      setIsCreateModalOpen(false);
    } finally {
      setCreating(false);
    }
  };

  const handleDeleteGroup = async (groupId: string) => {
    setDeletingGroupId(groupId);
    try {
      await apiClient.delete(`${API_AGENT_PREFIX}/groups/${groupId}`);
      toast.success("Группа удалена");
      if (expandedGroupId === groupId) {
        setExpandedGroupId(null);
      }
      setMembersByGroupId((prev) => {
        const next = { ...prev };
        delete next[groupId];
        return next;
      });
      await fetchGroups();
    } finally {
      setDeletingGroupId(null);
    }
  };

  const openEditModal = (group: AdminGroup) => {
    setEditingGroupId(group.id);
    setEditForm({
      name: group.name,
      description: group.description ?? "",
    });
    setIsEditModalOpen(true);
  };

  const handleUpdateGroup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingGroupId) return;

    setUpdatingGroup(true);
    try {
      await apiClient.patch(`${API_AGENT_PREFIX}/groups/${editingGroupId}`, {
        name: editForm.name,
        description: editForm.description || null,
      });
      toast.success("Группа обновлена");
      await fetchGroups();
      setIsEditModalOpen(false);
      setEditingGroupId(null);
      setEditForm(initialFormState);
    } finally {
      setUpdatingGroup(false);
    }
  };

  const toggleGroupMembers = async (groupId: string) => {
    if (expandedGroupId === groupId) {
      setExpandedGroupId(null);
      return;
    }

    setExpandedGroupId(groupId);
    if (!membersByGroupId[groupId]) {
      await fetchGroupMembers(groupId);
    }
  };

  const handleAddMember = async (groupId: string) => {
    const selectedUserIds = selectedUserIdsByGroupId[groupId] ?? [];
    if (selectedUserIds.length === 0) return;

    setAddingMemberFor(groupId);
    try {
      await apiClient.post(`${API_AGENT_PREFIX}/groups/${groupId}/users`, {
        user_ids: selectedUserIds,
      });
      toast.success("Участники добавлены в группу");
      await fetchGroupMembers(groupId);
      setSelectedUserIdsByGroupId((prev) => ({ ...prev, [groupId]: [] }));
    } finally {
      setAddingMemberFor(null);
    }
  };

  const handleRemoveMember = async (groupId: string, userId: string) => {
    const key = `${groupId}:${userId}`;
    setRemovingMemberKey(key);
    try {
      await apiClient.delete(
        `${API_AGENT_PREFIX}/groups/${groupId}/users/${userId}`,
      );
      toast.success("Участник удален из группы");
      await fetchGroupMembers(groupId);
    } finally {
      setRemovingMemberKey(null);
    }
  };

  const handleCreateModalOpenChange = (open: boolean) => {
    setIsCreateModalOpen(open);
    if (!open) {
      setForm(initialFormState);
    }
  };

  const handleEditModalOpenChange = (open: boolean) => {
    setIsEditModalOpen(open);
    if (!open) {
      setEditingGroupId(null);
      setEditForm(initialFormState);
    }
  };

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Группы</h2>
          <div className="flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto sm:flex-nowrap">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Поиск по названию / описанию"
              className="w-full sm:w-72"
            />
            <Button
              type="button"
              variant={"default2"}
              onClick={() => setIsCreateModalOpen(true)}
            >
              <Plus className="mr-2 size-4" />
              Добавить группу
            </Button>
          </div>
        </div>

        {(loadingGroups || loadingUsers) && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Загрузка данных...
          </div>
        )}

        {!loadingGroups &&
          filteredGroups.map((group) => {
            const members = membersByGroupId[group.id] ?? [];
            const isExpanded = expandedGroupId === group.id;
            const loadingMembers = loadingMembersFor === group.id;
            const selectedUserIds = selectedUserIdsByGroupId[group.id] ?? [];
            const currentMemberIds = new Set(members.map((m) => m.id));
            const availableUsers = allUsers.filter(
              (u) => !currentMemberIds.has(u.id),
            );
            const availableUserOptions = availableUsers.map((u) => {
              const fullName = `${u.first_name ?? ""} ${u.last_name ?? ""}`.trim();
              return {
                value: u.id,
                label: fullName ? `${u.email} (${fullName})` : u.email,
              };
            });

            return (
              <div
                key={group.id}
                className="border border-border rounded-lg overflow-hidden"
              >
                <div className="p-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <div className="font-medium">{group.name}</div>
                    <div className="text-sm text-muted-foreground">
                      {group.description || "Без описания"}
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <Badge variant="outline">
                      {members.length} участник(ов)
                    </Badge>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void toggleGroupMembers(group.id)}
                    >
                      <ChevronDown
                        className={`size-4 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                      />
                      <span className="ml-1">Участники</span>
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => openEditModal(group)}
                      disabled={updatingGroup}
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={deletingGroupId === group.id}
                      onClick={() => void handleDeleteGroup(group.id)}
                    >
                      {deletingGroupId === group.id ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <Trash2 className="size-4 text-destructive" />
                      )}
                    </Button>
                  </div>
                </div>

                {isExpanded && (
                  <div className="border-t border-border p-4 space-y-4 bg-muted/20">
                    <div className="flex flex-col md:flex-row gap-2 md:items-center">
                      <SearchableMultiSelect
                        className="w-full md:flex-1"
                        options={availableUserOptions}
                        values={selectedUserIds}
                        onValuesChange={(nextValues) =>
                          setSelectedUserIdsByGroupId((prev) => ({
                            ...prev,
                            [group.id]: nextValues,
                          }))
                        }
                        placeholder={
                          availableUsers.length > 0
                            ? "Выберите пользователей"
                            : "Нет доступных пользователей"
                        }
                        searchPlaceholder="Поиск пользователя..."
                        emptyText="Пользователи не найдены"
                        disabled={availableUsers.length === 0 || addingMemberFor === group.id}
                      />

                      <Button
                        type="button"
                        variant="outline"
                        disabled={
                          selectedUserIds.length === 0 ||
                          addingMemberFor === group.id ||
                          availableUsers.length === 0
                        }
                        onClick={() => void handleAddMember(group.id)}
                      >
                        {addingMemberFor === group.id ? (
                          <Loader2 className="mr-2 size-4 animate-spin" />
                        ) : (
                          <UserPlus className="mr-2 size-4" />
                        )}
                        Добавить участников
                      </Button>
                    </div>

                    {loadingMembers ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="size-4 animate-spin" />
                        Загрузка участников...
                      </div>
                    ) : members.length > 0 ? (
                      <div className="space-y-2">
                        {members.map((member) => {
                          const key = `${group.id}:${member.id}`;
                          const fullName =
                            `${member.first_name ?? ""} ${member.last_name ?? ""}`.trim();

                          return (
                            <div
                              key={member.id}
                              className="flex items-center justify-between bg-card border border-border rounded-md px-3 py-2"
                            >
                              <div>
                                <div className="text-sm font-medium">
                                  {member.email}
                                </div>
                                <div className="text-xs text-muted-foreground">
                                  {fullName || "Без имени"}
                                </div>
                              </div>
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                disabled={removingMemberKey === key}
                                onClick={() =>
                                  void handleRemoveMember(group.id, member.id)
                                }
                              >
                                {removingMemberKey === key ? (
                                  <Loader2 className="size-4 animate-spin" />
                                ) : (
                                  <Trash2 className="size-4 text-destructive" />
                                )}
                              </Button>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="text-sm text-muted-foreground">
                        В группе нет участников
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

        {!loadingGroups && filteredGroups.length === 0 && (
          <div className="text-sm text-muted-foreground">Группы не найдены</div>
        )}
      </div>

      <Dialog
        open={isCreateModalOpen}
        onOpenChange={handleCreateModalOpenChange}
      >
        <DialogContent className="w-full max-w-xl">
          <DialogHeader>
            <DialogTitle>Создать группу</DialogTitle>
            <DialogDescription>Заполните данные новой группы</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateGroup} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="admin-group-name">Название</Label>
              <Input
                id="admin-group-name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                disabled={creating}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="admin-group-description">Описание</Label>
              <Textarea
                id="admin-group-description"
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
                disabled={creating}
              />
            </div>

            <Button type="submit" disabled={creating}>
              {creating ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Создание...
                </>
              ) : (
                <>
                  <Plus className="mr-2 size-4" />
                  Создать
                </>
              )}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={isEditModalOpen} onOpenChange={handleEditModalOpenChange}>
        <DialogContent className="w-full max-w-xl">
          <DialogHeader>
            <DialogTitle>Редактировать группу</DialogTitle>
            <DialogDescription>Обновите название и описание группы</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleUpdateGroup} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="admin-edit-group-name">Название</Label>
              <Input
                id="admin-edit-group-name"
                value={editForm.name}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                required
                disabled={updatingGroup}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="admin-edit-group-description">Описание</Label>
              <Textarea
                id="admin-edit-group-description"
                value={editForm.description}
                onChange={(e) =>
                  setEditForm({ ...editForm, description: e.target.value })
                }
                disabled={updatingGroup}
              />
            </div>

            <Button type="submit" disabled={updatingGroup}>
              {updatingGroup ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Сохранение...
                </>
              ) : (
                <>
                  <Pencil className="mr-2 size-4" />
                  Сохранить
                </>
              )}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default AdminGroupsTab;
