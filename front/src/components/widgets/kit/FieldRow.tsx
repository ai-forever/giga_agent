import React from "react";
import {
  User,
  Flag,
  Clock,
  Folder,
  Tag,
  Calendar,
  Hash,
  CircleDot,
  type LucideIcon,
} from "lucide-react";

import type { IssueField } from "./types";

/** Имя иконки (из контракта) → компонент lucide. Provider-agnostic. */
const ICONS: Record<string, LucideIcon> = {
  user: User,
  flag: Flag,
  clock: Clock,
  folder: Folder,
  tag: Tag,
  calendar: Calendar,
  hash: Hash,
  status: CircleDot,
};

/**
 * Инлайн-поле карточки: иконка + значение. Подпись (label) уходит в title
 * для a11y/тултипа, чтобы не ломать компактную строку чипов.
 */
export const FieldRow: React.FC<{ field: IssueField }> = ({ field }) => {
  const Icon = field.icon ? ICONS[field.icon] : undefined;
  return (
    <span
      title={field.label}
      className="inline-flex items-center gap-1 text-muted-foreground"
    >
      {Icon && <Icon size={11} />}
      {field.value}
    </span>
  );
};
