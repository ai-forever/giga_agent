import { useEffect } from "react";
import { onMcpAuthorization } from "@/components/mcp/utils/callback.ts";

export function OAuthCallback() {
  useEffect(() => {
    (async () => {
      const params = new URLSearchParams(window.location.search);
      const code = params.get("code");
      const error = params.get("error");
      await onMcpAuthorization();
      try {
        const channel = new BroadcastChannel("mcp_auth");
        channel.postMessage({
          type: "mcp_auth_callback",
          success: !error,
          code,
          error,
        });
        channel.close();
      } catch (_e) {
        // Fallback на opener, если доступен (на случай отсутствия BroadcastChannel)
        if (window.opener) {
          window.opener.postMessage(
            {
              type: "mcp_auth_callback",
              success: !error,
              code,
              error,
            },
            window.location.origin,
          );
        }
      }
      window.close();
    })();
  }, []);

  return <div>Authentication successful. You can close this window.</div>;
}
