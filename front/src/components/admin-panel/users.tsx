import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Trash2, Loader2, Plus, Pencil } from "lucide-react";
import { toast } from "sonner";
import { AnimatePresence, motion } from "framer-motion";

import { API_AGENT_PREFIX, EXPERIMENTAL_MODE } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/components/providers/auth.tsx";
import { useConfirm } from "@/components/providers/confirm.tsx";
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
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AdminGroup, AdminUser } from "./types";
import { PasswordInput } from "@/components/ui/password-input.tsx";

type UserFormState = {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  is_superuser: boolean;
  experimental_mode: boolean;
  group_ids: string[];
  copy_owner_runtime_ids: boolean;
  copy_owner_module_secrets: boolean;
};

const initialFormState: UserFormState = {
  email: "",
  password: "",
  first_name: "",
  last_name: "",
  is_active: true,
  is_superuser: false,
  experimental_mode: true,
  group_ids: [],
  copy_owner_runtime_ids: false,
  copy_owner_module_secrets: false,
};

const initialEditFormState: UserFormState = {
  ...initialFormState,
};

const AdminUsersTab: React.FC = () => {
  const { user: currentUser } = useAuth();
  const confirm = useConfirm();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [groups, setGroups] = useState<AdminGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingGroups, setLoadingGroups] = useState(false);
  const [creating, setCreating] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isChangePassword, setIsChangePassword] = useState(false);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [form, setForm] = useState<UserFormState>(initialFormState);
  const [editForm, setEditForm] = useState<UserFormState>(initialEditFormState);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiClient.get<AdminUser[]>(
        `${API_AGENT_PREFIX}/auth/users`,
      );
      setUsers(data);
    } finally {
      setLoading(false);
    }
  }, []);

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

  // Потребление LLM за 30 дней (страница «Команда»): user_id → агрегат.
  const [usageByUser, setUsageByUser] = useState<
    Record<string, { requests: number; input_tokens: number; output_tokens: number }>
  >({});

  const fetchUsage = useCallback(async () => {
    try {
      const data = await apiClient.get<{
        users: {
          user_id: string;
          requests: number;
          input_tokens: number;
          output_tokens: number;
        }[];
      }>(`${API_AGENT_PREFIX}/auth/team/usage?days=30`);
      setUsageByUser(
        Object.fromEntries(data.users.map((u) => [u.user_id, u])),
      );
    } catch {
      // Не критично для списка пользователей.
    }
  }, []);

  useEffect(() => {
    void Promise.all([fetchUsers(), fetchGroups(), fetchUsage()]);
  }, [fetchUsers, fetchGroups, fetchUsage]);

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

  const filteredUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return users;

    return users.filter((u) => {
      const fullName = `${u.first_name ?? ""} ${u.last_name ?? ""}`.trim();
      return (
        u.email.toLowerCase().includes(q) ||
        fullName.toLowerCase().includes(q) ||
        (u.first_name ?? "").toLowerCase().includes(q) ||
        (u.last_name ?? "").toLowerCase().includes(q)
      );
    });
  }, [search, users]);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();

    setCreating(true);
    try {
      await apiClient.post(`${API_AGENT_PREFIX}/auth/users`, {
        email: form.email,
        password: form.password,
        first_name: form.first_name || null,
        last_name: form.last_name || null,
        is_active: form.is_active,
        is_superuser: form.is_superuser,
        ...(EXPERIMENTAL_MODE
          ? { experimental_mode: form.experimental_mode }
          : {}),
        group_ids: form.group_ids,
        copy_owner_runtime_ids: form.copy_owner_runtime_ids,
        copy_owner_module_secrets: form.copy_owner_module_secrets,
      });
      toast.success("Пользователь создан");
      setForm(initialFormState);
      await fetchUsers();
      setIsCreateModalOpen(false);
    } finally {
      setCreating(false);
    }
  };

  const handleDeleteUser = async (id: string) => {
    const targetUser = users.find((item) => item.id === id);
    const targetUserLabel = targetUser?.email
      ? `пользователя ${targetUser.email}`
      : "этого пользователя";
    const confirmed = await confirm({
      title: "Удалить пользователя?",
      description: `Вы уверены, что хотите удалить ${targetUserLabel}? Будут удалены связанные данные, включая файлы, чаты и прочее.`,
      confirmText: "Удалить",
      cancelText: "Отмена",
      variant: "destructive",
    });
    if (!confirmed) return;

    setDeletingUserId(id);
    try {
      await apiClient.delete(`${API_AGENT_PREFIX}/auth/users/${id}`);
      toast.success("Пользователь удален");
      await fetchUsers();
    } finally {
      setDeletingUserId(null);
    }
  };

  const openEditModal = (user: AdminUser) => {
    setEditingUserId(user.id);
    setIsChangePassword(false);
    setEditForm({
      email: user.email,
      password: "",
      first_name: user.first_name ?? "",
      last_name: user.last_name ?? "",
      is_active: user.is_active,
      is_superuser: user.is_superuser,
      experimental_mode: user.experimental_mode,
      group_ids: [],
      copy_owner_runtime_ids: false,
      copy_owner_module_secrets: false,
    });
    setIsEditModalOpen(true);
  };

  const handleUpdateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingUserId) return;

    const body: Record<string, unknown> = {
      email: editForm.email,
      first_name: editForm.first_name || null,
      last_name: editForm.last_name || null,
      is_active: editForm.is_active,
      is_superuser: editForm.is_superuser,
    };

    if (EXPERIMENTAL_MODE) {
      body.experimental_mode = editForm.experimental_mode;
    }

    if (isChangePassword) {
      body.password = editForm.password;
    }

    setUpdating(true);
    try {
      await apiClient.patch(
        `${API_AGENT_PREFIX}/auth/users/${editingUserId}`,
        body,
      );
      toast.success("Пользователь обновлен");
      await fetchUsers();
      setIsEditModalOpen(false);
      setEditingUserId(null);
      setIsChangePassword(false);
      setEditForm(initialEditFormState);
    } finally {
      setUpdating(false);
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
      setEditingUserId(null);
      setIsChangePassword(false);
      setEditForm(initialEditFormState);
    }
  };

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Пользователи</h2>
          <div className="flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto sm:flex-nowrap">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Поиск по email / имени"
              className="w-full sm:w-72"
            />
            <Button
              type="button"
              variant={"default2"}
              onClick={() => setIsCreateModalOpen(true)}
            >
              <Plus className="mr-2 size-4" />
              Добавить пользователя
            </Button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Загрузка пользователей...
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Имя</TableHead>
                <TableHead>Роль</TableHead>
                <TableHead>Статус</TableHead>
                <TableHead>Токены (30д)</TableHead>
                <TableHead className="text-right">Действия</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredUsers.map((u) => {
                const isSelf = currentUser?.id === u.id;
                const fullName =
                  `${u.first_name ?? ""} ${u.last_name ?? ""}`.trim();

                return (
                  <TableRow key={u.id}>
                    <TableCell
                      className="max-w-[280px] truncate"
                      title={u.email}
                    >
                      {u.email}
                    </TableCell>
                    <TableCell>{fullName || "-"}</TableCell>
                    <TableCell>
                      <Badge variant={u.is_superuser ? "default" : "outline"}>
                        {u.role ?? (u.is_superuser ? "admin" : "member")}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={u.is_active ? "default" : "secondary"}>
                        {u.is_active ? "Активен" : "Неактивен"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {(() => {
                        const usage = usageByUser[u.id];
                        if (!usage) {
                          return (
                            <span className="text-muted-foreground">—</span>
                          );
                        }
                        const total =
                          usage.input_tokens + usage.output_tokens;
                        return (
                          <span
                            title={`Запросов: ${usage.requests} · вход: ${usage.input_tokens.toLocaleString("ru-RU")} · выход: ${usage.output_tokens.toLocaleString("ru-RU")}`}
                          >
                            {total.toLocaleString("ru-RU")}
                            <span className="text-xs text-muted-foreground ml-1">
                              ({usage.requests} запр.)
                            </span>
                          </span>
                        );
                      })()}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => openEditModal(u)}
                          disabled={updating}
                        >
                          <Pencil className="size-4" />
                        </Button>
                        {isSelf ? (
                          <></>
                        ) : (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => void handleDeleteUser(u.id)}
                            disabled={deletingUserId === u.id}
                          >
                            {deletingUserId === u.id ? (
                              <Loader2 className="size-4 animate-spin" />
                            ) : (
                              <Trash2 className="size-4 text-destructive" />
                            )}
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}

              {filteredUsers.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="text-center text-muted-foreground"
                  >
                    Пользователи не найдены
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        )}
      </div>

      <Dialog
        open={isCreateModalOpen}
        onOpenChange={handleCreateModalOpenChange}
      >
        <DialogContent className="w-full max-w-2xl">
          <DialogHeader>
            <DialogTitle>Создать пользователя</DialogTitle>
            <DialogDescription>
              Заполните данные нового пользователя
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateUser} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="admin-user-email">Email</Label>
                <Input
                  id="admin-user-email"
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  required
                  disabled={creating}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="admin-user-password">Пароль</Label>
                <PasswordInput
                  id="admin-user-password"
                  value={form.password}
                  onChange={(e) =>
                    setForm({ ...form, password: e.target.value })
                  }
                  required
                  disabled={creating}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="admin-user-first-name">Имя</Label>
                <Input
                  id="admin-user-first-name"
                  value={form.first_name}
                  onChange={(e) =>
                    setForm({ ...form, first_name: e.target.value })
                  }
                  disabled={creating}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="admin-user-last-name">Фамилия</Label>
                <Input
                  id="admin-user-last-name"
                  value={form.last_name}
                  onChange={(e) =>
                    setForm({ ...form, last_name: e.target.value })
                  }
                  disabled={creating}
                />
              </div>
            </div>

            <div className="flex flex-wrap gap-6">
              <label className="flex items-center gap-2 text-sm">
                <Switch
                  checked={form.is_active}
                  onCheckedChange={(checked) =>
                    setForm({ ...form, is_active: checked })
                  }
                  disabled={creating}
                />
                Активен
              </label>
              <label className="flex items-center gap-2 text-sm">
                <Switch
                  checked={form.is_superuser}
                  onCheckedChange={(checked) =>
                    setForm({ ...form, is_superuser: checked })
                  }
                  disabled={creating}
                />
                Суперпользователь
              </label>
              {EXPERIMENTAL_MODE && (
                <label className="flex items-center gap-2 text-sm">
                  <Switch
                    checked={form.experimental_mode}
                    onCheckedChange={(checked) =>
                      setForm({ ...form, experimental_mode: checked })
                    }
                    disabled={creating}
                  />
                  Экспериментальный режим
                </label>
              )}
            </div>

            <div className="space-y-3">
              <div className="space-y-1.5">
                <label className="flex items-center gap-2 text-sm">
                  <Switch
                    checked={form.copy_owner_runtime_ids}
                    onCheckedChange={(checked) =>
                      setForm((prev) => ({
                        ...prev,
                        copy_owner_runtime_ids: checked,
                        copy_owner_module_secrets: checked
                          ? prev.copy_owner_module_secrets
                          : false,
                      }))
                    }
                    disabled={creating}
                  />
                  Назначить пользователю Ваши настройки LLM/Embeddings и т.д.
                </label>
                <p className="text-xs text-muted-foreground pl-12">
                  Ваши API-ключи подключений будут скрыты для него.
                </p>
              </div>

              <AnimatePresence initial={false}>
                {form.copy_owner_runtime_ids && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2, ease: "easeInOut" }}
                    className="overflow-hidden"
                  >
                    <div className="space-y-1.5">
                      <label className="flex items-center gap-2 text-sm">
                        <Switch
                          checked={form.copy_owner_module_secrets}
                          onCheckedChange={(checked) =>
                            setForm((prev) => ({
                              ...prev,
                              copy_owner_module_secrets: checked,
                            }))
                          }
                          disabled={creating}
                        />
                        Перенести API ключи модулей?
                      </label>
                      <p className="text-xs text-muted-foreground pl-12">
                        API ключи модулей будут доступны пользователю.
                      </p>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="admin-user-groups">Группы пользователя</Label>
              <SearchableMultiSelect
                className="w-full"
                options={groupOptions}
                values={form.group_ids}
                onValuesChange={(groupIds) =>
                  setForm({ ...form, group_ids: groupIds })
                }
                placeholder={
                  loadingGroups ? "Загрузка групп..." : "Выберите группы"
                }
                searchPlaceholder="Поиск группы..."
                emptyText="Группы не найдены"
                disabled={creating || loadingGroups}
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
        <DialogContent className="w-full max-w-2xl">
          <DialogHeader>
            <DialogTitle>Редактировать пользователя</DialogTitle>
            <DialogDescription>
              Обновите данные существующего пользователя
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleUpdateUser} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="admin-edit-user-email">Email</Label>
                <Input
                  id="admin-edit-user-email"
                  type="email"
                  value={editForm.email}
                  onChange={(e) =>
                    setEditForm({ ...editForm, email: e.target.value })
                  }
                  required
                  disabled={updating}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="admin-edit-user-first-name">Имя</Label>
                <Input
                  id="admin-edit-user-first-name"
                  value={editForm.first_name}
                  onChange={(e) =>
                    setEditForm({ ...editForm, first_name: e.target.value })
                  }
                  disabled={updating}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="admin-edit-user-last-name">Фамилия</Label>
                <Input
                  id="admin-edit-user-last-name"
                  value={editForm.last_name}
                  onChange={(e) =>
                    setEditForm({ ...editForm, last_name: e.target.value })
                  }
                  disabled={updating}
                />
              </div>
            </div>

            <div className="flex flex-wrap gap-6">
              <label className="flex items-center gap-2 text-sm">
                <Switch
                  checked={isChangePassword}
                  onCheckedChange={(checked) => {
                    setIsChangePassword(checked);
                    if (!checked) {
                      setEditForm({ ...editForm, password: "" });
                    }
                  }}
                  disabled={updating}
                />
                Изменить пароль
              </label>
            </div>

            {isChangePassword && (
              <div className="space-y-1.5">
                <Label htmlFor="admin-edit-user-password">Новый пароль</Label>
                <PasswordInput
                  id="admin-edit-user-password"
                  value={editForm.password}
                  onChange={(e) =>
                    setEditForm({ ...editForm, password: e.target.value })
                  }
                  disabled={updating}
                />
              </div>
            )}

            <div className="flex flex-wrap gap-6">
              <label className="flex items-center gap-2 text-sm">
                <Switch
                  checked={editForm.is_active}
                  onCheckedChange={(checked) =>
                    setEditForm({ ...editForm, is_active: checked })
                  }
                  disabled={updating || editingUserId === currentUser?.id}
                />
                Активен
              </label>
              <label className="flex items-center gap-2 text-sm">
                <Switch
                  checked={editForm.is_superuser}
                  onCheckedChange={(checked) =>
                    setEditForm({ ...editForm, is_superuser: checked })
                  }
                  disabled={updating || editingUserId === currentUser?.id}
                />
                Суперпользователь
              </label>
              {EXPERIMENTAL_MODE && (
                <label className="flex items-center gap-2 text-sm">
                  <Switch
                    checked={editForm.experimental_mode}
                    onCheckedChange={(checked) =>
                      setEditForm({ ...editForm, experimental_mode: checked })
                    }
                    disabled={updating}
                  />
                  Экспериментальный режим
                </label>
              )}
            </div>

            {editingUserId === currentUser?.id && (
              <p className="text-xs text-muted-foreground">
                Для текущего пользователя нельзя менять активность и роль.
              </p>
            )}

            <Button type="submit" disabled={updating}>
              {updating ? (
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

export default AdminUsersTab;
