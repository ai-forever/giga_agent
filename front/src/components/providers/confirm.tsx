import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

export type ConfirmOptions = {
  title?: string;
  description: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "default" | "destructive";
};

export type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

type ConfirmRequest = {
  options: ConfirmOptions;
  resolve: (result: boolean) => void;
};

const ConfirmContext = createContext<ConfirmFn | null>(null);

export const ConfirmProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const [activeRequest, setActiveRequest] = useState<ConfirmRequest | null>(
    null,
  );
  const [renderedRequest, setRenderedRequest] = useState<ConfirmRequest | null>(
    null,
  );
  const [isOpen, setIsOpen] = useState(false);
  const activeRequestRef = useRef<ConfirmRequest | null>(null);
  const queueRef = useRef<ConfirmRequest[]>([]);
  const pendingResultRef = useRef<boolean | null>(null);
  const closeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Fast Refresh can preserve state but reset refs; keep them consistent.
    activeRequestRef.current = activeRequest;
    if (activeRequest) {
      setRenderedRequest(activeRequest);
    }
  }, [activeRequest]);

  const showNext = useCallback(() => {
    if (
      activeRequest ||
      isOpen ||
      queueRef.current.length === 0
    ) {
      return;
    }
    const nextRequest = queueRef.current.shift();
    if (!nextRequest) return;
    pendingResultRef.current = null;
    activeRequestRef.current = nextRequest;
    setActiveRequest(nextRequest);
    setRenderedRequest(nextRequest);
    setIsOpen(true);
  }, [activeRequest, isOpen]);

  const settleCurrent = useCallback(
    (result: boolean) => {
      pendingResultRef.current = result;
      setIsOpen(false);
    },
    [],
  );

  const confirm = useCallback<ConfirmFn>(
    (options) =>
      new Promise<boolean>((resolve) => {
        queueRef.current.push({ options, resolve });
        showNext();
      }),
    [showNext],
  );

  // When the dialog is closing, keep `renderedRequest` stable for the duration
  // of the close animation (see `duration-200` in `AlertDialogContent`).
  useEffect(() => {
    if (isOpen) {
      if (closeTimeoutRef.current) {
        clearTimeout(closeTimeoutRef.current);
        closeTimeoutRef.current = null;
      }
      return;
    }

    const current = activeRequestRef.current ?? activeRequest;
    if (!current) return;

    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
    }

    closeTimeoutRef.current = setTimeout(() => {
      const latest = activeRequestRef.current ?? current;
      const result = pendingResultRef.current ?? false;
      pendingResultRef.current = null;
      latest?.resolve(result);

      activeRequestRef.current = null;
      setActiveRequest(null);
      setRenderedRequest(null);
      closeTimeoutRef.current = null;
    }, 210);

    return () => {
      if (closeTimeoutRef.current) {
        clearTimeout(closeTimeoutRef.current);
        closeTimeoutRef.current = null;
      }
    };
  }, [activeRequest, isOpen]);

  // Auto-advance the queue when idle.
  useEffect(() => {
    if (!activeRequest && !isOpen) {
      showNext();
    }
  }, [activeRequest, isOpen, showNext]);

  useEffect(
    () => () => {
      if (closeTimeoutRef.current) {
        clearTimeout(closeTimeoutRef.current);
        closeTimeoutRef.current = null;
      }

      (activeRequestRef.current ?? activeRequest)?.resolve(false);
      activeRequestRef.current = null;
      for (const request of queueRef.current) {
        request.resolve(false);
      }
      queueRef.current = [];
    },
    [],
  );

  const options = renderedRequest?.options;
  const isDestructive = options?.variant === "destructive";

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <AlertDialog
        open={isOpen}
        onOpenChange={(open) => {
          if (open) {
            setIsOpen(true);
            return;
          }

          // If the dialog is closing because of an Action/Cancel click,
          // `settleCurrent(...)` has already set `pendingResultRef`.
          if (pendingResultRef.current === null) {
            settleCurrent(false);
          } else {
            setIsOpen(false);
          }
        }}
      >
        <AlertDialogContent
          overlayProps={{
            onClick: (e) => {
              // Treat overlay click as "Cancel".
              if (pendingResultRef.current !== null) return;
              e.preventDefault();
              settleCurrent(false);
            },
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>
              {options?.title ?? "Подтверждение"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {options?.description ?? ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => settleCurrent(false)}>
              {options?.cancelText ?? "Отмена"}
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                variant={isDestructive ? "destructive" : "default"}
                onClick={() => settleCurrent(true)}
              >
                {options?.confirmText ?? "Подтвердить"}
              </Button>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ConfirmContext.Provider>
  );
};

export const useConfirm = (): ConfirmFn => {
  const context = useContext(ConfirmContext);
  if (!context) {
    throw new Error("useConfirm must be used within a ConfirmProvider");
  }
  return context;
};
