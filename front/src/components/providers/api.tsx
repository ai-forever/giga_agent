import { useEffect, PropsWithChildren } from "react";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { apiClient, ApiError } from "@/lib/api-client";
import { useAuth } from "./auth";

/**
 * Провайдер для связывания API клиента с React-контекстом.
 * Настраивает обработку токена, ошибок и редиректы.
 *
 * Должен быть размещён внутри AuthProvider и BrowserRouter.
 */
export const ApiProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const { token, logout } = useAuth();
  const navigate = useNavigate();

  // Синхронизация токена с API клиентом
  useEffect(() => {
    apiClient.setToken(token);
  }, [token]);

  // Настройка обработчиков ошибок
  useEffect(() => {
    // Обработка 401 ошибки
    apiClient.setUnauthorizedHandler(() => {
      toast.error("Сессия истекла", {
        description: "Пожалуйста, войдите в систему снова",
        richColors: true,
      });
      logout();
      navigate("/login");
    });

    // Обработка остальных ошибок
    apiClient.setErrorHandler((error: ApiError) => {
      // Формируем сообщение в зависимости от типа ошибки
      let title = "Ошибка";
      let description = error.message;

      if (error.isForbidden()) {
        title = "Доступ запрещён";
        description = "У вас нет прав для выполнения этого действия";
      } else if (error.isNotFound()) {
        title = "Не найдено";
        description = "Запрашиваемый ресурс не существует";
      } else if (error.isValidationError()) {
        title = "Ошибка валидации";
        // Попробуем извлечь детали валидации
        if (error.data && typeof error.data === "object") {
          const data = error.data as Record<string, unknown>;
          if (Array.isArray(data.detail)) {
            description = data.detail
              .map((d: { msg?: string }) => d.msg || String(d))
              .join(", ");
          }
        }
      } else if (error.isServerError()) {
        title = "Ошибка сервера";
        description = "Произошла внутренняя ошибка. Попробуйте позже";
      }

      toast.error(title, {
        description,
        richColors: true,
      });
    });
  }, [logout, navigate]);

  return <>{children}</>;
};
