import React, { useCallback, useEffect, useRef, useState } from "react";
import { LayoutGrid, Settings2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import ConnectorsCatalogTab from "./catalog-tab";
import ConnectorsConnectedTab from "./connected-tab";
import type { UseConnectorsResult } from "./use-connectors";

export type ConnectorsTab = "catalog" | "connected";

// Сколько подсвечивать карточку после автоперехода на «Подключённые».
const HIGHLIGHT_MS = 3000;

interface ConnectorsModalProps {
  isOpen: boolean;
  onClose: () => void;
  api: UseConnectorsResult;
  initialTab: ConnectorsTab;
}

const ConnectorsModal: React.FC<ConnectorsModalProps> = ({
  isOpen,
  onClose,
  api,
  initialTab,
}) => {
  const [tab, setTab] = useState<ConnectorsTab>(initialTab);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const highlightTimer = useRef<number | null>(null);

  useEffect(() => {
    if (isOpen) setTab(initialTab);
  }, [isOpen, initialTab]);

  useEffect(
    () => () => {
      if (highlightTimer.current) window.clearTimeout(highlightTimer.current);
    },
    [],
  );

  // После подключения — показать «Подключённые» и подсветить новую карточку.
  const showConnected = useCallback((id: string | null) => {
    setTab("connected");
    setHighlightId(id);
    if (highlightTimer.current) window.clearTimeout(highlightTimer.current);
    if (id) {
      highlightTimer.current = window.setTimeout(
        () => setHighlightId(null),
        HIGHLIGHT_MS,
      );
    }
  }, []);

  const tabContentClass =
    "flex-1 min-h-0 flex-col gap-4 data-[state=active]:flex data-[state=inactive]:hidden";

  return (
    <Dialog open={isOpen} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl h-[85vh] flex flex-col gap-4">
        <DialogHeader>
          <DialogTitle>Коннекторы</DialogTitle>
          <DialogDescription>
            Подключайте сервисы из каталога и управляйте активными коннекторами.
          </DialogDescription>
        </DialogHeader>

        <Tabs
          value={tab}
          onValueChange={(v) => setTab(v as ConnectorsTab)}
          className="flex-1 min-h-0 flex flex-col gap-4"
        >
          <TabsList className="w-full">
            <TabsTrigger value="catalog">
              <LayoutGrid className="size-4" />
              Каталог
            </TabsTrigger>
            <TabsTrigger value="connected">
              <Settings2 className="size-4" />
              Подключённые
            </TabsTrigger>
          </TabsList>

          {/* forceMount — чтобы поиск и открытые формы переживали переключение вкладок. */}
          <TabsContent value="catalog" forceMount className={tabContentClass}>
            <ConnectorsCatalogTab api={api} onConnected={showConnected} />
          </TabsContent>
          <TabsContent value="connected" forceMount className={tabContentClass}>
            <ConnectorsConnectedTab
              api={api}
              highlightId={tab === "connected" ? highlightId : null}
            />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
};

export default ConnectorsModal;
