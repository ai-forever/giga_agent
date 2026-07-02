import { useCallback, useEffect, useRef } from "react";

/**
 * Opens an OAuth provider URL in a popup and resolves when the backend callback
 * posts back a `{ type, success }` message. Mirrors the MCP OAuth popup flow.
 */
export function useOAuthPopup(
  messageType: string,
  onResult: (success: boolean, data: any) => void,
) {
  const windowRef = useRef<Window | null>(null);
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const data = event.data;
      if (!data || data.type !== messageType) return;
      onResultRef.current(Boolean(data.success), data);
      try {
        windowRef.current?.close();
      } catch {
        /* noop */
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [messageType]);

  return useCallback((url: string) => {
    windowRef.current = window.open(url, "oauth_popup", "width=520,height=720");
  }, []);
}
