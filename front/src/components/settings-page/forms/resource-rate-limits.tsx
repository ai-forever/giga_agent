import React, { useEffect, useState } from "react";

import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { API_AGENT_PREFIX } from "@/config.ts";
import { apiClient } from "@/lib/api-client";
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
import type {
  PermissionResourceType,
  RateLimitPeriod,
  RateLimitResponse,
} from "./types";
import { RATE_LIMIT_PERIODS } from "./types";

interface ResourceRateLimitsProps {
  resourceType: PermissionResourceType;
  resourceId: string;
  canManage: boolean;
  disabled?: boolean;
  defaultOpen?: boolean;
}

const PERIOD_LABELS: Record<RateLimitPeriod, string> = {
  second: "в секунду",
  minute: "в минуту",
  hour: "в час",
};

/** Parse a number input: empty -> null (no limit), otherwise a positive integer. */
const parseLimit = (raw: string): number | null => {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const value = Number.parseInt(trimmed, 10);
  if (!Number.isFinite(value) || value < 1) return null;
  return value;
};

const ResourceRateLimits: React.FC<ResourceRateLimitsProps> = ({
  resourceType,
  resourceId,
  canManage,
  disabled = false,
  defaultOpen = false,
}) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [exists, setExists] = useState(false);
  const [requestsGlobal, setRequestsGlobal] = useState("");
  const [requestsPerUser, setRequestsPerUser] = useState("");
  const [period, setPeriod] = useState<RateLimitPeriod>("minute");
  const [isActive, setIsActive] = useState(true);

  useEffect(() => {
    if (!canManage || !resourceId) return;

    let cancelled = false;
    setLoading(true);
    void apiClient
      .get<RateLimitResponse | null>(
        `${API_AGENT_PREFIX}/rate-limits/${resourceType}/${resourceId}`,
      )
      .then((data) => {
        if (cancelled) return;
        if (data) {
          setExists(true);
          setRequestsGlobal(
            data.requests_global != null ? String(data.requests_global) : "",
          );
          setRequestsPerUser(
            data.requests_per_user != null
              ? String(data.requests_per_user)
              : "",
          );
          setPeriod(data.period);
          setIsActive(data.is_active);
        } else {
          setExists(false);
        }
      })
      .catch(() => {
        if (!cancelled) setExists(false);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [canManage, resourceType, resourceId]);

  if (!canManage || !resourceId) {
    return null;
  }

  const isDisabled = disabled || loading || saving;
  const globalValue = parseLimit(requestsGlobal);
  const perUserValue = parseLimit(requestsPerUser);

  const handleSave = async () => {
    if (isDisabled) return;
    if (globalValue == null && perUserValue == null) {
      toast.error("Укажите хотя бы один лимит (общий или на пользователя)");
      return;
    }
    try {
      setSaving(true);
      await apiClient.put(
        `${API_AGENT_PREFIX}/rate-limits/${resourceType}/${resourceId}`,
        {
          requests_global: globalValue,
          requests_per_user: perUserValue,
          period,
          settings: {},
          is_active: isActive,
        },
      );
      setExists(true);
      toast.success("Лимит сохранён");
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (isDisabled || !exists) return;
    try {
      setSaving(true);
      await apiClient.delete(
        `${API_AGENT_PREFIX}/rate-limits/${resourceType}/${resourceId}`,
      );
      setExists(false);
      setRequestsGlobal("");
      setRequestsPerUser("");
      setPeriod("minute");
      setIsActive(true);
      toast.success("Лимит удалён");
    } catch {
      // handled globally
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className="flex items-center gap-2 w-full py-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <div className="flex-1 h-px bg-border" />
        <span className="flex items-center gap-1.5">
          Ограничение частоты запросов
          {exists && (
            <span className="text-xs text-foreground/70">(настроено)</span>
          )}
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
                <h4 className="text-sm font-medium">
                  Ограничение частоты запросов
                </h4>
                <p className="text-xs text-muted-foreground mt-1">
                  Лимит запросов к ресурсу. Пусто — без ограничения по этому
                  измерению.
                </p>
              </div>

              {loading && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  Загрузка лимита...
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <Label htmlFor="rate-limit-global">
                    Общий лимит (на всех)
                  </Label>
                  <Input
                    id="rate-limit-global"
                    type="number"
                    min={1}
                    value={requestsGlobal}
                    onChange={(e) => setRequestsGlobal(e.target.value)}
                    placeholder="Без ограничения"
                    disabled={isDisabled}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="rate-limit-per-user">
                    Лимит на пользователя
                  </Label>
                  <Input
                    id="rate-limit-per-user"
                    type="number"
                    min={1}
                    value={requestsPerUser}
                    onChange={(e) => setRequestsPerUser(e.target.value)}
                    placeholder="Без ограничения"
                    disabled={isDisabled}
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="rate-limit-period">Период</Label>
                <Select
                  value={period}
                  onValueChange={(value) => setPeriod(value as RateLimitPeriod)}
                  disabled={isDisabled}
                >
                  <SelectTrigger id="rate-limit-period">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {RATE_LIMIT_PERIODS.map((option) => (
                      <SelectItem key={option} value={option}>
                        {PERIOD_LABELS[option]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Например: {globalValue ?? "—"} запросов{" "}
                  {PERIOD_LABELS[period]} суммарно, {perUserValue ?? "—"}{" "}
                  {PERIOD_LABELS[period]} на пользователя.
                </p>
              </div>

              <div className="flex items-center justify-between rounded-md border border-border p-3">
                <Label htmlFor="rate-limit-active" className="cursor-pointer">
                  Лимит включён
                </Label>
                <Switch
                  id="rate-limit-active"
                  checked={isActive}
                  onCheckedChange={setIsActive}
                  disabled={isDisabled}
                />
              </div>

              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  onClick={handleSave}
                  disabled={isDisabled}
                >
                  Сохранить лимит
                </Button>
                {exists && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={handleDelete}
                    disabled={isDisabled}
                  >
                    Удалить лимит
                  </Button>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ResourceRateLimits;
