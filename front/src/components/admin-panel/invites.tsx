import React, { useCallback, useEffect, useState } from "react";
import { Copy, Link2, Loader2, Plus, XCircle } from "lucide-react";
import { toast } from "sonner";

import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Invite = {
  id: string;
  email: string | null;
  role: string;
  max_uses: number;
  used_count: number;
  expires_at: string;
  revoked_at: string | null;
  created_at: string;
  copy_runtime_ids: boolean;
};

type InviteCreated = Invite & { token: string; join_path: string };

type FormState = {
  email: string;
  role: "member" | "admin";
  max_uses: number;
  expires_in_days: number;
  copy_runtime_ids: boolean;
};

const initialForm: FormState = {
  email: "",
  role: "member",
  max_uses: 1,
  expires_in_days: 7,
  copy_runtime_ids: true,
};

const inviteStatus = (invite: Invite): { label: string; variant: "default" | "outline" | "destructive" | "secondary" } => {
  if (invite.revoked_at) return { label: "Отозвано", variant: "destructive" };
  if (new Date(invite.expires_at) <= new Date())
    return { label: "Истекло", variant: "secondary" };
  if (invite.used_count >= invite.max_uses)
    return { label: "Использовано", variant: "secondary" };
  return { label: "Активно", variant: "default" };
};

const AdminInvitesTab: React.FC = () => {
  const confirm = useConfirm();
  const [invites, setInvites] = useState<Invite[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<FormState>(initialForm);
  const [creating, setCreating] = useState(false);
  // Ссылка показывается один раз после создания.
  const [createdLink, setCreatedLink] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiClient.get<Invite[]>(
        `${API_AGENT_PREFIX}/auth/invites`,
      );
      setInvites(data);
    } catch {
      toast.error("Не удалось загрузить приглашения");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const body: Record<string, unknown> = {
        role: form.role,
        max_uses: form.max_uses,
        expires_in_days: form.expires_in_days,
        copy_runtime_ids: form.copy_runtime_ids,
      };
      if (form.email.trim()) body.email = form.email.trim();
      const created = await apiClient.post<InviteCreated>(
        `${API_AGENT_PREFIX}/auth/invites`,
        body,
      );
      const url = `${window.location.origin}/join/${created.token}`;
      setCreatedLink(url);
      setForm(initialForm);
      await load();
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Не удалось создать приглашение",
      );
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (invite: Invite) => {
    const ok = await confirm({
      title: "Отозвать приглашение?",
      description: "Ссылка перестанет работать. Это действие необратимо.",
    });
    if (!ok) return;
    try {
      await apiClient.delete(`${API_AGENT_PREFIX}/auth/invites/${invite.id}`);
      toast.success("Приглашение отозвано");
      await load();
    } catch {
      toast.error("Не удалось отозвать приглашение");
    }
  };

  const copyLink = async (url: string) => {
    await navigator.clipboard.writeText(url);
    toast.success("Ссылка скопирована");
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Ссылки-приглашения в команду. Токен показывается один раз при
          создании — скопируйте и отправьте приглашённому.
        </p>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4 mr-1" /> Пригласить
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : invites.length === 0 ? (
        <div className="text-sm text-muted-foreground py-8 text-center">
          Приглашений пока нет
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Статус</TableHead>
              <TableHead>Роль</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Использований</TableHead>
              <TableHead>Истекает</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {invites.map((invite) => {
              const st = inviteStatus(invite);
              return (
                <TableRow key={invite.id}>
                  <TableCell>
                    <Badge variant={st.variant}>{st.label}</Badge>
                  </TableCell>
                  <TableCell>{invite.role}</TableCell>
                  <TableCell>{invite.email ?? "—"}</TableCell>
                  <TableCell>
                    {invite.used_count}/{invite.max_uses}
                  </TableCell>
                  <TableCell>
                    {new Date(invite.expires_at).toLocaleDateString("ru-RU")}
                  </TableCell>
                  <TableCell className="text-right">
                    {st.label === "Активно" && (
                      <Button
                        variant="ghost"
                        size="sm"
                        title="Отозвать"
                        onClick={() => void handleRevoke(invite)}
                      >
                        <XCircle className="h-4 w-4 text-destructive" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}

      {/* Диалог создания */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Пригласить в команду</DialogTitle>
            <DialogDescription>
              Будет создана ссылка-приглашение. Отправьте её любым удобным
              способом.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Роль</Label>
              <Select
                value={form.role}
                onValueChange={(v) =>
                  setForm((f) => ({ ...f, role: v as FormState["role"] }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="member">Участник (member)</SelectItem>
                  <SelectItem value="admin">Администратор (admin)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="invite-email">
                Email (необязательно — ограничить конкретной почтой)
              </Label>
              <Input
                id="invite-email"
                type="email"
                placeholder="user@example.com"
                value={form.email}
                onChange={(e) =>
                  setForm((f) => ({ ...f, email: e.target.value }))
                }
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="invite-uses">Максимум использований</Label>
                <Input
                  id="invite-uses"
                  type="number"
                  min={1}
                  max={1000}
                  value={form.max_uses}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      max_uses: Math.max(1, Number(e.target.value) || 1),
                    }))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="invite-days">Срок действия (дней)</Label>
                <Input
                  id="invite-days"
                  type="number"
                  min={1}
                  max={90}
                  value={form.expires_in_days}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      expires_in_days: Math.max(1, Number(e.target.value) || 7),
                    }))
                  }
                />
              </div>
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="invite-copy" className="cursor-pointer">
                Скопировать мои настройки LLM приглашённому
              </Label>
              <Switch
                id="invite-copy"
                checked={form.copy_runtime_ids}
                onCheckedChange={(checked) =>
                  setForm((f) => ({ ...f, copy_runtime_ids: checked }))
                }
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setCreateOpen(false)}>
                Отмена
              </Button>
              <Button onClick={() => void handleCreate()} disabled={creating}>
                {creating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Создать ссылку"
                )}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Диалог «ссылка создана» — показывается один раз */}
      <Dialog
        open={createdLink !== null}
        onOpenChange={(open) => {
          if (!open) {
            setCreatedLink(null);
            setCreateOpen(false);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Link2 className="h-5 w-5" /> Ссылка-приглашение готова
            </DialogTitle>
            <DialogDescription>
              Скопируйте сейчас — повторно ссылка не показывается (в системе
              хранится только её отпечаток).
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2">
            <Input readOnly value={createdLink ?? ""} className="font-mono" />
            <Button
              variant="outline"
              size="icon"
              onClick={() => createdLink && void copyLink(createdLink)}
              title="Скопировать"
            >
              <Copy className="h-4 w-4" />
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default AdminInvitesTab;
