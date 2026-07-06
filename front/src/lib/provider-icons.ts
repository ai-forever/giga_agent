import yandexDisk from "@/assets/integrations/yandex/YandexDisk.png";
import yandexMail from "@/assets/integrations/yandex/Yandex_Mail_icon.svg";
import yandexCalendar from "@/assets/integrations/yandex/Yandex_Calendar_icon.svg";

/**
 * Локальные иконки провайдеров/модулей по их ключу (module_id / provider_key).
 * Перекрывают дефолтный фавикон, который бэкенд отдаёт в поле `icon` (иначе у
 * всех сервисов Яндекса один общий фавикон yandex.ru).
 */
const LOCAL_PROVIDER_ICONS: Record<string, string> = {
  yandex_disk: yandexDisk,
  yandex_mail: yandexMail,
  yandex_calendar: yandexCalendar,
};

/** Локальный ассет-иконка для ключа провайдера/модуля, если задан. */
export function localProviderIcon(key?: string | null): string | undefined {
  return key ? LOCAL_PROVIDER_ICONS[key] : undefined;
}

/** Иконка провайдера: локальный ассет по ключу либо бэкендовый фолбэк. */
export function resolveProviderIcon(
  key?: string | null,
  fallback?: string | null,
): string | null {
  return localProviderIcon(key) ?? fallback ?? null;
}
