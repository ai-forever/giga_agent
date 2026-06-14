/**
 * Нормализованный provider-agnostic контракт трекерных виджетов.
 *
 * Любой бэкенд-провайдер (Яндекс.Трекер, Jira, Linear, мок) приводит свои
 * данные к этой форме — фронту-киту всё равно, чей это трекер. `provider` =
 * module_id, из него StatusBadge строит REST-базу `/{provider}/issues/{key}/…`.
 */

export interface IssueField {
  /** Имя иконки из ICONS (FieldRow). Неизвестное/пустое — без иконки. */
  icon?: string;
  /** Человекочитаемая подпись (a11y/тултип); инлайн не показывается. */
  label?: string;
  value: string;
}

export interface Issue {
  id: string;
  key: string;
  title: string;
  status?: string;
  /** module_id провайдера — драйвит REST-эндпоинты переходов. */
  provider: string;
  description?: string;
  /** Чип у ключа (очередь/проект/борд). */
  tag?: string;
  /** Произвольные поля карточки (исполнитель, приоритет, дата…). */
  fields?: IssueField[];
}

/** Нормализованный payload результата тула, который рендерит Board. */
export interface IssueBoardPayload {
  widget: "issue_board";
  provider: string;
  issues: Issue[];
  /** Опциональная группировка: ключ поля label или "status". */
  groupBy?: string;
  error?: string;
}

export type Accent = "success" | "info" | "warning" | "danger";

/** Группа генеративной доски (агент собрал её в рантайме). */
export interface IssueGroup {
  label: string;
  accent?: Accent;
  issues: Issue[];
}

/** Композиция генеративной доски, пришедшая через push_ui_message. */
export interface Composition {
  provider: string;
  title?: string;
  groups: IssueGroup[];
}

/** Запись файлового браузера (файл или папка). */
export interface FileEntry {
  name: string;
  path: string;
  type: "dir" | "file";
  size?: number;
  modified?: string;
  mime_type?: string;
  public_url?: string;
}

/** Нормализованный payload файлового браузера (provider-agnostic). */
export interface FileBrowserPayload {
  widget: "file_browser";
  provider: string;
  path: string;
  entries: FileEntry[];
}

/** Письмо в списке входящих (краткое; тело подгружается по клику). */
export interface MailMessage {
  id: string;
  from?: string;
  subject?: string;
  date?: string;
  /** Тело — приходит при чтении (REST /read), не в списке. */
  body?: string;
  to?: string;
  truncated?: boolean;
}

/** Нормализованный payload входящих (provider-agnostic). */
export interface MailInboxPayload {
  widget: "mail_inbox";
  provider: string;
  folder: string;
  messages: MailMessage[];
}

/** Событие календаря. start/end — ISO; дата-только = весь день. */
export interface CalendarEvent {
  uid: string;
  calendar?: string;
  summary: string;
  start?: string;
  end?: string;
  location?: string;
}

/** Нормализованный payload агенды (provider-agnostic). */
export interface CalendarAgendaPayload {
  widget: "calendar_agenda";
  provider: string;
  days: number;
  events: CalendarEvent[];
}

/** Payload месяц-грида (year + month 1–12 + события месяца). */
export interface CalendarMonthPayload {
  widget: "calendar_month";
  provider: string;
  year: number;
  month: number;
  events: CalendarEvent[];
}
