/**
 * Чистый API клиент без зависимостей от React.
 * Обработка ошибок и UI-уведомления настраиваются через ApiProvider.
 */

export type ApiErrorHandler = (error: ApiError) => void;

export interface RequestOptions extends Omit<RequestInit, "method" | "body"> {
  /**
   * Если false, глобальный обработчик ошибок не будет вызван.
   * Полезно когда нужно обработать ошибку локально.
   * @default true
   */
  showError?: boolean;
  /**
   * Тип ответа.
   * @default "json"
   */
  responseType?: "json" | "text";
  /**
   * Добавлять Authorization header из установленного токена.
   * @default true
   */
  attachAuth?: boolean;
}

type RedirectInstruction = {
  kind: "redirect";
  url: string;
};

const REDIRECT_INSTRUCTION_MEDIA_TYPE =
  "application/vnd.giga-agent.redirect+json";

function isRedirectInstruction(value: unknown): value is RedirectInstruction {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return record.kind === "redirect" && typeof record.url === "string";
}

class ApiClient {
  private token: string | null = null;
  private onError: ApiErrorHandler = () => {};
  private onUnauthorized: () => void = () => {};

  /**
   * Установить токен авторизации
   */
  setToken(token: string | null) {
    this.token = token;
  }

  /**
   * Установить глобальный обработчик ошибок (кроме 401)
   */
  setErrorHandler(handler: ApiErrorHandler) {
    this.onError = handler;
  }

  /**
   * Установить обработчик 401 ошибки (unauthorized)
   */
  setUnauthorizedHandler(handler: () => void) {
    this.onUnauthorized = handler;
  }

  /**
   * Базовый метод для выполнения запросов
   */
  async request<T>(
    method: string,
    url: string,
    data?: unknown,
    options: RequestOptions = {},
  ): Promise<T> {
    const {
      showError = true,
      responseType = "json",
      attachAuth = true,
      ...fetchOptions
    } = options;

    const headers: Record<string, string> = {
      ...((fetchOptions.headers as Record<string, string>) || {}),
    };

    if (attachAuth && this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    // Автоматически добавляем Content-Type для JSON, но не для FormData
    if (data && !(data instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }

    const response = await fetch(url, {
      ...fetchOptions,
      credentials: fetchOptions.credentials ?? "include",
      method,
      headers,
      body:
        data instanceof FormData
          ? data
          : data
            ? JSON.stringify(data)
            : undefined,
    });

    if (!response.ok) {
      let errorMessage = `Ошибка ${response.status}`;
      let errorData: unknown = undefined;

      try {
        errorData = await response.json();
        if (typeof errorData === "object" && errorData !== null) {
          const err = errorData as Record<string, unknown>;
          errorMessage =
            (err.detail as string) || (err.message as string) || errorMessage;
        }
      } catch {
        errorMessage = response.statusText || errorMessage;
      }

      const error = new ApiError(errorMessage, response.status, errorData);

      if (response.status === 401) {
        this.onUnauthorized();
        throw error;
      }

      if (showError) {
        this.onError(error);
      }

      throw error;
    }

    const text = await response.text();
    if (responseType === "text") {
      return text as T;
    }
    return text ? JSON.parse(text) : (null as T);
  }

  /**
   * GET запрос
   */
  get<T>(url: string, options?: RequestOptions): Promise<T> {
    return this.request<T>("GET", url, undefined, options);
  }

  /**
   * GET запрос, возвращающий сырой текст.
   */
  getText(url: string, options?: RequestOptions): Promise<string> {
    return this.request<string>("GET", url, undefined, {
      ...options,
      responseType: "text",
    });
  }

  /**
   * GET запрос, возвращающий текст. Если API вместо 307 отдаёт JSON-инструкцию
   * `{kind:"redirect", url:"..."}`, выполняет второй запрос на указанный URL
   * без auth и cookies (`credentials:"omit"`).
   */
  async getTextWithRedirectInstruction(
    url: string,
    options: RequestOptions = {},
  ): Promise<string> {
    const { showError = true, attachAuth = true, ...fetchOptions } = options;

    const headers: Record<string, string> = {
      ...((fetchOptions.headers as Record<string, string>) || {}),
    };

    if (attachAuth && this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    const response = await fetch(url, {
      ...fetchOptions,
      credentials: fetchOptions.credentials ?? "omit",
      method: "GET",
      headers,
    });

    if (!response.ok) {
      let errorMessage = `Ошибка ${response.status}`;
      let errorData: unknown = undefined;

      try {
        errorData = await response.json();
        if (typeof errorData === "object" && errorData !== null) {
          const err = errorData as Record<string, unknown>;
          errorMessage =
            (err.detail as string) || (err.message as string) || errorMessage;
        }
      } catch {
        errorMessage = response.statusText || errorMessage;
      }

      const error = new ApiError(errorMessage, response.status, errorData);

      if (response.status === 401) {
        this.onUnauthorized();
        throw error;
      }

      if (showError) {
        this.onError(error);
      }

      throw error;
    }

    const raw = await response.text();
    const contentType = (response.headers.get("content-type") || "")
      .split(";")[0]
      .trim()
      .toLowerCase();

    if (contentType === REDIRECT_INSTRUCTION_MEDIA_TYPE) {
      let parsed: unknown = null;
      try {
        parsed = raw ? (JSON.parse(raw) as unknown) : null;
      } catch {
        return raw;
      }

      if (isRedirectInstruction(parsed)) {
        const externalResponse = await fetch(parsed.url, {
          method: "GET",
          credentials: "omit",
          signal: fetchOptions.signal,
        });

        if (!externalResponse.ok) {
          const error = new ApiError(
            `Ошибка ${externalResponse.status}`,
            externalResponse.status,
          );
          if (showError) {
            this.onError(error);
          }
          throw error;
        }

        return await externalResponse.text();
      }
    }

    return raw;
  }

  /**
   * POST запрос
   */
  post<T>(url: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>("POST", url, data, options);
  }

  /**
   * PUT запрос
   */
  put<T>(url: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>("PUT", url, data, options);
  }

  /**
   * PATCH запрос
   */
  patch<T>(url: string, data?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>("PATCH", url, data, options);
  }

  /**
   * DELETE запрос
   */
  delete<T>(url: string, options?: RequestOptions): Promise<T> {
    return this.request<T>("DELETE", url, undefined, options);
  }
}

/**
 * Класс ошибки API с дополнительной информацией
 */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly data?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /**
   * Проверка на ошибку авторизации
   */
  isUnauthorized(): boolean {
    return this.status === 401;
  }

  /**
   * Проверка на ошибку доступа
   */
  isForbidden(): boolean {
    return this.status === 403;
  }

  /**
   * Проверка на ошибку "не найдено"
   */
  isNotFound(): boolean {
    return this.status === 404;
  }

  /**
   * Проверка на ошибку валидации
   */
  isValidationError(): boolean {
    return this.status === 422;
  }

  /**
   * Проверка на конфликт (например, 409)
   */
  isConflict(): boolean {
    return this.status === 409;
  }

  /**
   * Проверка на серверную ошибку
   */
  isServerError(): boolean {
    return this.status >= 500;
  }
}

/**
 * Singleton экземпляр API клиента.
 * Используйте напрямую или через хук useApi().
 */
export const apiClient = new ApiClient();
