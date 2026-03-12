# Observability для локального запуска

> 🚧 **В разработке**

Этот раздел описывает настройку трассировки и мониторинга для локального запуска GigaAgent через `pip install` и `giga_agent run dev`.

## Статус

По умолчанию Observability (Phoenix, Langfuse, OpenTelemetry) настроен для Docker-окружения через переменные окружения в `.env`.

Для локального запуска потребуется:
- Настройка OTLP endpoints
- Конфигурация exporters
- Запуск локальных инстансов Phoenix/Langfuse (опционально)

## Планируемое содержание

1. Установка Phoenix локально
2. Установка Langfuse локально  
3. Настройка OpenTelemetry для local dev
4. Примеры конфигурации `.env` для локального запуска
5. Troubleshooting

## Как помочь

Если вы настроили Observability локально, поделитесь вашей конфигурацией через issue или PR!
