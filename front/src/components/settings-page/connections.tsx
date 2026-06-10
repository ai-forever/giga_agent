import React from "react";

import { YandexConnect } from "@/components/settings-page/yandex-connect";
import { useAuth } from "@/components/providers/auth.tsx";

/**
 * Вкладка «Подключения» — единый дом для всех сервисов, которые подключаются
 * по OAuth (кнопкой, а не ручным вводом токена). Сейчас здесь Яндекс
 * (Диск/Трекер/Почта); сюда же добавляются будущие OAuth-интеграции.
 */
export const ConnectionsSettings: React.FC = () => {
  const { refreshUser } = useAuth();
  return (
    <div className="space-y-5">
      <div className="space-y-1.5">
        <h2 className="text-lg font-semibold">Подключения</h2>
        <p className="text-sm text-muted-foreground">
          Подключайте внешние сервисы по OAuth — токен сохраняется и обновляется
          автоматически, без ручного ввода ключей.
        </p>
      </div>

      <YandexConnect onChanged={refreshUser} />
    </div>
  );
};
