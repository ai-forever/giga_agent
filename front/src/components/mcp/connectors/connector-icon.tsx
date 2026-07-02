import React, { useEffect, useState } from "react";
import { Plug } from "lucide-react";

import { cn } from "@/lib/utils";

interface ConnectorIconProps {
  // URL иконки/фавиконки; null — иконки нет.
  src?: string | null;
  className?: string;
}

/**
 * Иконка коннектора с фолбэком на <Plug/>. Используется для нативных модулей и
 * MCP-серверов (в т.ч. кастомных, где src — это фавиконка домена, которая может
 * не загрузиться). При ошибке загрузки показываем плейсхолдер вместо пустоты.
 */
const ConnectorIcon: React.FC<ConnectorIconProps> = ({ src, className }) => {
  const [failed, setFailed] = useState(false);

  // Сбросить состояние ошибки, когда меняется источник иконки.
  useEffect(() => {
    setFailed(false);
  }, [src]);

  if (!src || failed) {
    return <Plug className={cn("shrink-0 text-muted-foreground", className)} />;
  }

  return (
    <img
      src={src}
      alt=""
      className={cn("rounded shrink-0", className)}
      onError={() => setFailed(true)}
    />
  );
};

export default ConnectorIcon;
