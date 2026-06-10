# yandex_oauth — общий OAuth-флоу Яндекса

Сервисный модуль (пустой `label`, без тулов). Заменяет ручной ввод токенов
Яндекс.Диска и Яндекс.Трекера на кнопку «Подключить» с авто-обновлением токена.

## Зачем

Раньше пользователь сам получал OAuth-токен в Яндексе и вставлял его в
«API-ключи модулей». Токен Яндекса живёт ~1 год и не обновлялся — после
истечения всё молча ломалось. Этот модуль:

- даёт кнопку «Подключить» (popup → согласие → токен сохраняется сам);
- хранит `refresh_token` и срок жизни, **прозрачно обновляет** access-токен;
- сохраняет обратную совместимость: ранее введённый вручную токен работает как
  fallback (без refresh).

## Архитектура

Один зарегистрированный Яндекс-аппликейшн обслуживает оба модуля. Scope
запрашивается **под конкретный модуль** в момент авторизации, токены пишутся в
**разные** секреты — Диск и Трекер подключаются раздельно.

```
service.py   чистый OAuth-слой: конфиг приложения, реестр модулей (scope +
             имена секретов), authorize-URL, exchange/refresh (httpx). Без БД.
state.py     подписанный state: HMAC-SHA256(secret_key) над {user, module, flow,
             exp}. Минтится только на аутентифицированном /start → callback'у не
             нужны куки, identity берётся из подписи.
tokens.py    хранилище токенов в user.secrets + прозрачный refresh. Точка, через
             которую тулы получают валидный access-токен (get_valid_access_token).
router.py    /start /callback /exchange /disconnect /status.
module.py    YandexOAuthModule — монтирует router на /agent/yandex_oauth.
```

### Реестр модулей (`service.MODULES`)

| module_id      | scope                                            | access-секрет (= legacy ручной) |
|----------------|--------------------------------------------------|----------------------------------|
| yandex_disk    | `cloud_api:disk.{read,write,info,app_folder}`    | `YANDEX_DISK_ACCESS_TOKEN`       |
| yandex_tracker | `tracker:read`, `tracker:write`                  | `YANDEX_TRACKER_OAUTH_TOKEN`     |

Имена access-секретов совпадают с прежними ручными — поэтому `is_enabled()` и
тулы менять не пришлось, а старые токены продолжают работать. Дополнительно
хранятся `*_REFRESH_TOKEN` и `*_TOKEN_EXPIRES_AT`. У Трекера org-id остаётся
отдельным ручным секретом (`YANDEX_TRACKER_ORG_ID`) — из OAuth он не приходит.

## Два флоу подключения

- **Server-callback** (если задан redirect_uri): popup открывает согласие →
  Яндекс редиректит на `/agent/yandex_oauth/callback` → код меняется на токены →
  callback отдаёт HTML, который `postMessage`'ит опенеру и закрывается.
- **Verification code** (fallback, если redirect_uri не настроен): согласие
  открывается во вкладке, Яндекс показывает код, пользователь вставляет его в
  поле → `POST /exchange`.

`/start` выбирает флоу автоматически: callback, если доступен redirect_uri,
иначе code. Можно форсировать `?flow=callback|code`.

## Конфигурация (env)

| Переменная                   | Назначение                                                      |
|------------------------------|----------------------------------------------------------------|
| `YANDEX_OAUTH_CLIENT_ID`     | ClientID приложения Яндекса. Без него фича выключена.           |
| `YANDEX_OAUTH_CLIENT_SECRET` | Client secret приложения.                                      |
| `YANDEX_OAUTH_REDIRECT_URI`  | redirect_uri для server-callback. Если пуст — берётся из        |
|                              | `GIGA_AGENT_BASE_URL` + `/agent/yandex_oauth/callback`.         |

> ⚠️ При стандартном dev-развёртывании nginx проксирует `/api/agent/` → backend
> `/agent/`. Поэтому публичный redirect_uri —
> `http://localhost:8123/api/agent/yandex_oauth/callback` (через `/api`).
> Авто-сборка из `GIGA_AGENT_BASE_URL` даёт `/agent/...` без `/api`, что nginx не
> проксирует, — задавайте `YANDEX_OAUTH_REDIRECT_URI` явно.

> ℹ️ `docker restart` НЕ перечитывает `env_file`. После правки `.env` пересоздайте
> контейнер: `docker compose -p giga_agent_dev -f docker-compose.dev.yml up -d
> giga-agent`.

Если `client_id/secret` не заданы — `/status` отдаёт `configured: false`, фронт
скрывает блок «Подключение Яндекса», всё работает на ручных токенах.

## Refresh

`tokens.get_valid_access_token(runtime, module_id)`:

1. читает access/refresh/expires из секретов пользователя;
2. access свежий (или нет expiry) → отдаёт как есть;
3. протух и есть refresh → `service.refresh_access_token`, пишет новые токены в
   БД, инвалидирует кэш, отдаёт новый access;
4. есть только access без refresh (ручной токен) → отдаёт как есть;
5. иначе → ошибка «не подключён».

Тулы Диска/Трекера зовут эту функцию и про срок жизни не знают.

## Как добавить ещё один Яндекс-модуль

1. Добавь запись в `service.MODULES` (scope + имена секретов).
2. В `auth.py` модуля получай токен через
   `yandex_oauth.tokens.get_valid_access_token(runtime, "<module_id>")`.
3. Добавь модуль в список на фронте (`yandex-connect.tsx`).
