import React, { useEffect, useState } from "react";
import { Plug } from "lucide-react";

import { cn } from "@/lib/utils";
import { localProviderIcon } from "@/lib/provider-icons";

interface ConnectorIconProps {
  // URL иконки/фавиконки; null — иконки нет.
  src?: string | null;
  // Ключ провайдера/модуля (module_id): если для него есть локальный ассет —
  // он перекрывает src (иначе у всех сервисов Яндекса общий фавикон).
  iconKey?: string | null;
  className?: string;
}

/**
 * Иконка коннектора с фолбэком на <Plug/>. Используется для нативных модулей и
 * MCP-серверов (в т.ч. кастомных, где src — это фавиконка домена, которая может
 * не загрузиться). При ошибке загрузки показываем плейсхолдер вместо пустоты.
 */
const ConnectorIcon: React.FC<ConnectorIconProps> = ({
  src,
  iconKey,
  className,
}) => {
  const [failed, setFailed] = useState(false);
  const effectiveSrc = localProviderIcon(iconKey) ?? src;

  // Сбросить состояние ошибки, когда меняется источник иконки.
  useEffect(() => {
    setFailed(false);
  }, [effectiveSrc]);

  if (!effectiveSrc || failed) {
    return <Plug className={cn("shrink-0 text-muted-foreground", className)} />;
  }

  return (
    <img
      src={effectiveSrc}
      alt=""
      className={cn("rounded shrink-0", className)}
      onError={() => setFailed(true)}
    />
  );
};

export default ConnectorIcon;
