import React, { useEffect, useRef, useState } from "react";
import { AppWindow, X } from "lucide-react";
import { apiClient } from "@/lib/api-client";
import { API_AGENT_PREFIX } from "@/config.ts";
import OverlayPortal from "../OverlayPortal.tsx";

/**
 * Host side of the MCP Apps (interactive widget) protocol.
 *
 * An MCP App tool (``meta.ui.resourceUri``) ships a self-contained HTML app that
 * runs in a sandboxed iframe and speaks JSON-RPC (protocol "2025-11-21") to its
 * host over ``postMessage``. The widget is the *client*; this component is the
 * *host/server*. Flow:
 *
 *   widget → request  ui/initialize            → host replies {hostInfo, …}
 *   widget → notify   ui/notifications/initialized
 *   host   → notify   ui/notifications/tool-input   {arguments}   ← draws content
 *   host   → notify   ui/notifications/tool-result  {structuredContent}
 *   widget → request  tools/call                → host proxies to /ui-call
 *   widget → notify   ui/notifications/size-changed {height}      ← autosize
 *
 * The widget HTML and the proxied tool calls both go through the backend
 * (``/ui-resource`` and ``/ui-call``), which gates calls to app-visible tools.
 */

const MCP_SERVERS_URL = `${API_AGENT_PREFIX}/mcp/servers`;
const PROTOCOL_VERSION = "2025-11-21";
const MIN_HEIGHT = 220;
const MAX_HEIGHT = 900;
const FS_HEADER_H = 48; // fullscreen header bar height (px)

interface McpUiWidgetProps {
  serverRef: string;
  resourceUri: string;
  toolName: string;
  appName?: string;
  iconUrl?: string | null;
  toolArgs?: Record<string, unknown> | null;
  structuredContent?: Record<string, unknown> | null;
}

type JsonRpc = {
  jsonrpc?: string;
  id?: string | number;
  method?: string;
  params?: any;
};

const McpUiWidget: React.FC<McpUiWidgetProps> = ({
  serverRef,
  resourceUri,
  toolName,
  appName,
  iconUrl,
  toolArgs,
  structuredContent,
}) => {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState<number>(480);
  const [loaded, setLoaded] = useState(false);
  const [displayMode, setDisplayMode] = useState<"inline" | "fullscreen">(
    "inline",
  );
  // The widget asks the host to open links (popups are disabled in the iframe).
  // We surface a chooser instead of auto-opening — auto window.open after an
  // async round-trip is popup-blocked, and showing the URL is safer UX.
  const [pendingLink, setPendingLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [iconError, setIconError] = useState(false);

  // The widget HTML is loaded directly from our API (not srcDoc): a real
  // navigation lets the backend enforce the CSP response header and keeps the
  // iframe opaque-origin (sandbox without allow-same-origin) for isolation.
  // Auth rides the session cookie (the endpoint accepts it).
  const src =
    `${MCP_SERVERS_URL}/${encodeURIComponent(serverRef)}/ui-resource` +
    `?uri=${encodeURIComponent(resourceUri)}`;

  // Reset the fade-in when the loaded document changes.
  useEffect(() => setLoaded(false), [src]);

  // Host bridge: implement the ui/* JSON-RPC server over postMessage.
  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    let initialized = false;
    const post = (msg: object) => iframe.contentWindow?.postMessage(msg, "*");
    const reply = (id: string | number | undefined, result: object) =>
      id !== undefined && post({ jsonrpc: "2.0", id, result });
    const replyError = (
      id: string | number | undefined,
      code: number,
      message: string,
    ) =>
      id !== undefined &&
      post({ jsonrpc: "2.0", id, error: { code, message } });

    const pushToolData = () => {
      // Primary render path: the widget draws from the call *arguments*.
      post({
        jsonrpc: "2.0",
        method: "ui/notifications/tool-input",
        params: { arguments: toolArgs ?? {} },
      });
      // Follow-up data (e.g. checkpoint id) for later edits/restore.
      post({
        jsonrpc: "2.0",
        method: "ui/notifications/tool-result",
        params: {
          content: [],
          structuredContent: structuredContent ?? undefined,
          isError: false,
        },
      });
    };

    const theme = document.documentElement.classList.contains("dark")
      ? "dark"
      : "light";

    const onMessage = async (ev: MessageEvent) => {
      if (ev.source !== iframe.contentWindow) return;
      const msg = ev.data as JsonRpc;
      if (!msg || msg.jsonrpc !== "2.0" || typeof msg.method !== "string")
        return;
      const { id, method, params } = msg;

      switch (method) {
        case "ui/initialize":
          reply(id, {
            protocolVersion: PROTOCOL_VERSION,
            hostInfo: { name: "giga_agent", version: "1.0.0" },
            hostCapabilities: { openLinks: {} },
            hostContext: { theme },
          });
          return;

        case "ui/notifications/initialized":
          if (!initialized) {
            initialized = true;
            pushToolData();
          }
          return;

        case "tools/call":
          try {
            const res = (await apiClient.post(
              `${MCP_SERVERS_URL}/${encodeURIComponent(serverRef)}/ui-call`,
              { tool: params?.name, arguments: params?.arguments ?? {} },
              { showError: false },
            )) as Record<string, unknown>;
            // The widget validates the reply against the MCP CallToolResultSchema,
            // where ``structuredContent`` is ``.optional()`` — i.e. it accepts
            // ``undefined`` but REJECTS ``null``. The backend sends ``null`` when a
            // tool has no structured output, which fails zod and makes the widget
            // silently drop the result. Strip the key when it's nullish.
            const result: Record<string, unknown> = {
              content: Array.isArray(res?.content) ? res.content : [],
              isError: Boolean(res?.isError),
            };
            if (res?.structuredContent != null) {
              result.structuredContent = res.structuredContent;
            }
            reply(id, result);
          } catch (e: any) {
            replyError(id, -32000, e?.message || "ui-call failed");
          }
          return;

        case "ui/notifications/size-changed": {
          const h = Number(params?.height);
          if (Number.isFinite(h) && h > 0) {
            setHeight(Math.min(Math.max(h, MIN_HEIGHT), MAX_HEIGHT));
          }
          return;
        }

        case "ui/open-link": {
          const url = params?.url;
          const ok = typeof url === "string" && /^https?:\/\//i.test(url);
          if (ok) {
            setCopied(false);
            setPendingLink(url);
          }
          // We "handled" it by presenting the chooser; the user decides next.
          reply(id, { isError: !ok });
          return;
        }

        case "ui/request-display-mode": {
          // Honour inline/fullscreen (pip falls back to inline). The reply MUST
          // echo a concrete mode — the widget validates it (zod) and only then
          // switches its own layout; an empty reply makes "Edit" silently fail.
          const requested =
            params?.mode === "fullscreen" ? "fullscreen" : "inline";
          setDisplayMode(requested);
          reply(id, { mode: requested });
          return;
        }

        default:
          // Ack any other request so the widget doesn't hang waiting; ignore
          // unrecognised notifications (no id).
          reply(id, {});
          return;
      }
    };

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [serverRef, toolArgs, structuredContent]);

  // Esc exits the fullscreen modal from the host side too (the widget's own Esc
  // only fires while the iframe is focused).
  useEffect(() => {
    if (displayMode !== "fullscreen") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setDisplayMode("inline");
      iframeRef.current?.contentWindow?.postMessage(
        {
          jsonrpc: "2.0",
          method: "ui/notifications/host-context-changed",
          params: { displayMode: "inline" },
        },
        "*",
      );
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [displayMode]);

  // In fullscreen the widget sizes its <main> to host-provided containerDimensions
  // (without them it collapses to a small box). Feed it the modal's pixel size
  // and keep it in sync on resize.
  useEffect(() => {
    if (displayMode !== "fullscreen") return;
    const sync = () => {
      const el = iframeRef.current;
      if (!el) return;
      el.contentWindow?.postMessage(
        {
          jsonrpc: "2.0",
          method: "ui/notifications/host-context-changed",
          params: {
            containerDimensions: {
              height: el.clientHeight,
              width: el.clientWidth,
            },
          },
        },
        "*",
      );
    };
    const raf = requestAnimationFrame(sync);
    window.addEventListener("resize", sync);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", sync);
    };
  }, [displayMode]);

  const fullscreen = displayMode === "fullscreen";

  const copyLink = async () => {
    if (!pendingLink) return;
    try {
      await navigator.clipboard.writeText(pendingLink);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = pendingLink;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
  };

  const openLinkInNewTab = () => {
    if (!pendingLink) return;
    // Triggered by a real click → fresh user activation, so not popup-blocked.
    window.open(pendingLink, "_blank", "noopener,noreferrer");
    setPendingLink(null);
  };

  const exitFullscreen = () => {
    setDisplayMode("inline");
    // Tell the widget to revert its own layout — otherwise it keeps its
    // fullscreen sizing while our container shrinks back to inline.
    iframeRef.current?.contentWindow?.postMessage(
      {
        jsonrpc: "2.0",
        method: "ui/notifications/host-context-changed",
        params: { displayMode: "inline" },
      },
      "*",
    );
  };

  const renderAppIcon = (size: number) =>
    iconUrl && !iconError ? (
      <img
        src={iconUrl}
        alt=""
        width={size}
        height={size}
        style={{ borderRadius: 3 }}
        onError={() => setIconError(true)}
      />
    ) : (
      <AppWindow size={size} />
    );

  // The SAME iframe node persists across modes — only its styling changes.
  // Re-mounting (e.g. via a portal) would reload the widget and drop the user's
  // in-canvas edits and the live bridge handshake. (Conditional siblings keep
  // the iframe at a stable child index, so toggling headers doesn't remount it.)
  return (
    <>
      {!fullscreen && (
        <div className="mb-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
          {renderAppIcon(14)}
          <span className="font-medium text-foreground/80">
            {appName || toolName}
          </span>
        </div>
      )}
      <iframe
        ref={iframeRef}
        title={`mcp-widget-${toolName}`}
        src={src}
        onLoad={() => setLoaded(true)}
        // allow-same-origin: the widget keeps the /ui-resource origin (its own,
        // cross-origin to the app) so it can use real localStorage/clipboard.
        // SAFE ONLY while /ui-resource is served from a different origin than the
        // app — otherwise the widget could read the app's storage/cookies.
        sandbox="allow-scripts allow-same-origin"
        allow="fullscreen; clipboard-write"
        style={
          fullscreen
            ? {
                // Full-window takeover: header on top, iframe fills the rest.
                // Explicit width/height (not just insets) so the widget gets a
                // real box to size into.
                position: "fixed",
                top: FS_HEADER_H,
                left: 0,
                width: "100vw",
                height: `calc(100vh - ${FS_HEADER_H}px)`,
                border: "none",
                zIndex: 1000,
                background: "var(--background, #fff)",
              }
            : {
                width: "100%",
                height,
                border: "none",
                borderRadius: 8,
                background: "transparent",
                opacity: loaded ? 1 : 0,
                transition: "opacity 0.15s ease",
              }
        }
      />
      {fullscreen && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            height: FS_HEADER_H,
            zIndex: 1001,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 8px 0 14px",
            background: "var(--card, #1e1e1e)",
            borderBottom: "1px solid var(--border, #333)",
            color: "var(--foreground, #fff)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 14,
              fontWeight: 500,
            }}
          >
            {renderAppIcon(16)}
            <span>{appName || toolName}</span>
          </div>
          <button
            type="button"
            aria-label="Закрыть"
            onClick={exitFullscreen}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 32,
              height: 32,
              borderRadius: 8,
              border: "none",
              background: "transparent",
              color: "inherit",
              cursor: "pointer",
            }}
          >
            <X size={18} />
          </button>
        </div>
      )}

      <OverlayPortal
        isVisible={!!pendingLink}
        onClose={() => setPendingLink(null)}
      >
        <div className="flex w-[420px] max-w-[90vw] flex-col gap-3 rounded-lg bg-card p-5 text-foreground">
          <div className="text-sm font-medium">Виджет хочет открыть ссылку</div>
          <input
            type="text"
            readOnly
            value={pendingLink ?? ""}
            onFocus={(e) => e.currentTarget.select()}
            className="w-full rounded-md border border-border bg-muted px-3 py-2 text-xs text-foreground outline-none"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={copyLink}
              className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-muted"
            >
              {copied ? "Скопировано ✓" : "Скопировать"}
            </button>
            <button
              type="button"
              onClick={openLinkInNewTab}
              className="rounded-md bg-primary px-3 py-1.5 text-xs text-primary-foreground hover:opacity-90"
            >
              Открыть в новой вкладке
            </button>
          </div>
        </div>
      </OverlayPortal>
    </>
  );
};

export default McpUiWidget;
