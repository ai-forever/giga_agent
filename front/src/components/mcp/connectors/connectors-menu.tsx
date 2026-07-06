import React from "react";
import { Blocks, Settings2 } from "lucide-react";

import {
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { useUserInfo } from "@/components/providers/user-info-context.ts";
import ConnectorIcon from "./connector-icon";
import { iconForConnector } from "./types";

/**
 * Подменю «Коннекторы» в plus-меню composer'а.
 * Рендерится как прямой потомок DropdownMenuContent.
 */
const ConnectorsMenu: React.FC = () => {
  const {
    connectors: api,
    openConnectors,
    toggleModule,
    enabledModules,
  } = useUserInfo();
  const { connectors, catalog, moduleCatalog, toggleActive } = api;
  const connectedModules = moduleCatalog.filter(
    (m) => m.status === "connected",
  );
  const hasAny = connectors.length > 0 || connectedModules.length > 0;

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger className="gap-2">
        <Blocks className="size-5" />
        <span>Коннекторы</span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="min-w-[260px] max-h-[60vh] overflow-y-auto p-2 space-y-1">
        <DropdownMenuItem
          onSelect={() => openConnectors(hasAny ? "connected" : "catalog")}
          className="gap-2"
        >
          <Settings2 className="size-4" />
          <span>Настроить коннекторы</span>
        </DropdownMenuItem>

        {(connectors.length > 0 || connectedModules.length > 0) && (
          <DropdownMenuSeparator />
        )}

        {connectors.length === 0 && connectedModules.length === 0 && (
          <div className="px-2 py-3 text-xs text-muted-foreground text-center">
            Нет коннекторов
          </div>
        )}

        {connectedModules.map((m) => (
          <div
            key={`module:${m.module_id}`}
            className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-accent"
          >
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <ConnectorIcon
                src={m.icon}
                iconKey={m.module_id}
                className="size-5"
              />
              <span className="text-sm truncate max-w-[200px]">{m.name}</span>
            </div>
            <Switch
              checked={enabledModules[m.module_id] ?? m.enabled}
              onCheckedChange={(checked) =>
                toggleModule(m.module_id, Boolean(checked))
              }
            />
          </div>
        ))}

        {connectors.map((c) => {
          const icon = iconForConnector(c, catalog);
          return (
            <div
              key={`${c.source}:${c.id}`}
              className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-accent"
            >
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <ConnectorIcon src={icon} className="size-5" />
                <span className="text-sm truncate max-w-[200px]">{c.name}</span>
                {c.source === "file" && (
                  <span className="text-[10px] text-muted-foreground shrink-0">
                    local
                  </span>
                )}
              </div>
              <Switch
                checked={c.is_active}
                onCheckedChange={(checked) =>
                  toggleActive(c.id, Boolean(checked))
                }
              />
            </div>
          );
        })}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
};

export default ConnectorsMenu;
