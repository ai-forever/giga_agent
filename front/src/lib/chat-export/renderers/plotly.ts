import { apiClient } from "@/lib/api-client";
import { buildContentByPathPreviewUrl } from "@/components/attachments/file-utils";

async function getPlotly(): Promise<any> {
  // @ts-ignore — no type declarations for plotly bundle
  const mod = await import("plotly.js/dist/plotly");
  return (mod as any).default ?? mod;
}

function countSubplots(layout: any): { cols: number; rows: number } {
  if (!layout || typeof layout !== "object") return { cols: 1, rows: 1 };
  let maxX = 1;
  let maxY = 1;
  for (const key of Object.keys(layout)) {
    const xMatch = /^xaxis(\d+)?$/.exec(key);
    if (xMatch) {
      const n = xMatch[1] ? Number(xMatch[1]) : 1;
      if (n > maxX) maxX = n;
      continue;
    }
    const yMatch = /^yaxis(\d+)?$/.exec(key);
    if (yMatch) {
      const n = yMatch[1] ? Number(yMatch[1]) : 1;
      if (n > maxY) maxY = n;
    }
  }
  // Subplots tend to scale roughly as sqrt(N); cols=rows=ceil(sqrt(max)).
  const total = Math.max(maxX, maxY);
  const side = Math.ceil(Math.sqrt(total));
  return { cols: side, rows: side };
}

function resolveSize(layout: any): { width: number; height: number } {
  const wRaw = Number(layout?.width);
  const hRaw = Number(layout?.height);
  if (wRaw > 0 && hRaw > 0) return { width: wRaw, height: hRaw };

  const { cols, rows } = countSubplots(layout);
  // ~420×320 per subplot — достаточно, чтобы подписи осей и тики не налазили.
  const width = wRaw > 0 ? wRaw : Math.max(900, cols * 420);
  const height = hRaw > 0 ? hRaw : Math.max(500, rows * 320);
  return { width, height };
}

export async function renderPlotlyToPng(
  figureJson: any,
): Promise<{ dataUrl: string; width: number; height: number }> {
  const Plotly = await getPlotly();
  const { width, height } = resolveSize(figureJson?.layout);

  const container = document.createElement("div");
  container.style.position = "fixed";
  container.style.left = "-9999px";
  container.style.top = "-9999px";
  container.style.width = `${width}px`;
  container.style.height = `${height}px`;
  document.body.appendChild(container);
  try {
    await Plotly.newPlot(
      container,
      figureJson.data,
      {
        ...figureJson.layout,
        autosize: false,
        template: "plotly_white",
        paper_bgcolor: "#fff",
        plot_bgcolor: "#fff",
        font: { color: "#111", ...(figureJson.layout?.font ?? {}) },
        width,
        height,
      },
      { staticPlot: true },
    );
    const dataUrl: string = await Plotly.toImage(container, {
      format: "png",
      width,
      height,
      scale: 2,
    });
    return { dataUrl, width, height };
  } finally {
    Plotly.purge(container);
    container.remove();
  }
}

export async function fetchPlotlyFigure(path: string): Promise<any> {
  const raw = await apiClient.getTextWithRedirectInstruction(
    buildContentByPathPreviewUrl(path),
    { attachAuth: true, credentials: "same-origin", showError: false },
  );
  return JSON.parse(raw);
}
