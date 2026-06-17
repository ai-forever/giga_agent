import { blobToDataUrl } from "../utils";

export interface MermaidPngResult {
  dataUrl: string;
  blob: Blob;
  aspectRatio: number;
}

let _mermaidPromise: Promise<any> | null = null;

function getMermaid(): Promise<any> {
  if (!_mermaidPromise) {
    _mermaidPromise = import("mermaid").then((m) => {
      const mermaid = m.default;
      mermaid.initialize({
        startOnLoad: false,
        theme: "default",
        securityLevel: "loose",
      });
      return mermaid;
    });
  }
  return _mermaidPromise;
}

/**
 * Replaces every `<foreignObject>` in a Mermaid SVG with an equivalent
 * `<text>`/`<tspan>` block. Two birds: keeps node labels visible (Mermaid puts
 * them in HTML by default) AND removes the foreignObject elements that taint
 * canvas on `drawImage` → `toBlob`.
 *
 * We compute glyph position from the foreignObject's own (x, y, width,
 * height) box so the text lands roughly centred inside the original node.
 */
function inlineForeignObjectsAsSvgText(svgString: string): string {
  if (!svgString.includes("<foreignObject")) return svgString;
  const parser = new DOMParser();
  const doc = parser.parseFromString(svgString, "image/svg+xml");
  if (doc.querySelector("parsererror")) return svgString;

  const SVG_NS = "http://www.w3.org/2000/svg";
  const foreignObjects = Array.from(doc.querySelectorAll("foreignObject"));
  for (const fo of foreignObjects) {
    const x = parseFloat(fo.getAttribute("x") ?? "0") || 0;
    const yAttr = parseFloat(fo.getAttribute("y") ?? "0") || 0;
    const w = parseFloat(fo.getAttribute("width") ?? "100") || 100;
    const h = parseFloat(fo.getAttribute("height") ?? "20") || 20;

    // Extract plain text. Treat <br>, <div>, <p> as line breaks.
    const inner = fo.firstElementChild ?? fo;
    const html = (inner as Element).innerHTML ?? "";
    const lines = html
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/(div|p|li)>/gi, "\n")
      .replace(/<[^>]+>/g, "")
      .replace(/&nbsp;/gi, " ")
      .replace(/&amp;/gi, "&")
      .replace(/&lt;/gi, "<")
      .replace(/&gt;/gi, ">")
      .split(/\n+/)
      .map((s) => s.trim())
      .filter(Boolean);

    if (lines.length === 0) {
      fo.remove();
      continue;
    }

    const fontSize = 13;
    const lineHeight = fontSize * 1.15;
    const totalH = lineHeight * lines.length;
    const startY = yAttr + h / 2 - totalH / 2 + lineHeight * 0.75;

    const textEl = doc.createElementNS(SVG_NS, "text");
    textEl.setAttribute("x", String(x + w / 2));
    textEl.setAttribute("y", String(startY));
    textEl.setAttribute("text-anchor", "middle");
    textEl.setAttribute("font-family", "Arial, Helvetica, sans-serif");
    textEl.setAttribute("font-size", String(fontSize));
    textEl.setAttribute("fill", "#111");

    for (let i = 0; i < lines.length; i++) {
      const tspan = doc.createElementNS(SVG_NS, "tspan");
      tspan.setAttribute("x", String(x + w / 2));
      tspan.setAttribute("dy", i === 0 ? "0" : String(lineHeight));
      tspan.textContent = lines[i];
      textEl.appendChild(tspan);
    }

    fo.parentNode?.replaceChild(textEl, fo);
  }

  return new XMLSerializer().serializeToString(doc);
}

export async function renderMermaidToPng(
  chart: string,
  targetWidth = 800,
): Promise<MermaidPngResult | null> {
  try {
    const mermaid = await getMermaid();
    const id = `mermaid-export-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const { svg: rawSvg } = await mermaid.render(id, chart);
    const el = document.getElementById(id);
    if (el) el.remove();

    // Convert foreignObject (HTML-inside-SVG) labels to plain SVG text:
    // foreignObject taints the canvas on drawImage → toBlob throws SecurityError.
    // Doing the conversion (instead of stripping) preserves the node labels.
    const svg = inlineForeignObjectsAsSvgText(rawSvg);

    const parser = new DOMParser();
    const svgDoc = parser.parseFromString(svg, "image/svg+xml");
    const svgEl = svgDoc.querySelector("svg");
    let aspectRatio = 0.5;
    if (svgEl) {
      const vb = svgEl.getAttribute("viewBox");
      const sw = svgEl.getAttribute("width");
      const sh = svgEl.getAttribute("height");
      if (vb) {
        const parts = vb
          .trim()
          .split(/[\s,]+/)
          .map(Number);
        if (parts.length >= 4 && parts[2] > 0) {
          aspectRatio = parts[3] / parts[2];
        }
      } else if (sw && sh) {
        const pw = parseFloat(sw);
        const ph = parseFloat(sh);
        if (pw > 0) aspectRatio = ph / pw;
      }
    }

    const height = Math.max(Math.round(targetWidth * aspectRatio), 50);
    const canvas = document.createElement("canvas");
    canvas.width = targetWidth;
    canvas.height = height;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, targetWidth, height);

    const svgBlob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
    const objectUrl = URL.createObjectURL(svgBlob);

    const blob = await new Promise<Blob>((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        ctx.drawImage(img, 0, 0, targetWidth, height);
        URL.revokeObjectURL(objectUrl);
        canvas.toBlob(
          (b) => (b ? resolve(b) : reject(new Error("toBlob failed"))),
          "image/png",
        );
      };
      img.onerror = () => {
        URL.revokeObjectURL(objectUrl);
        reject(new Error("Failed to load SVG as image"));
      };
      img.src = objectUrl;
    });

    const dataUrl = await blobToDataUrl(blob);
    return { dataUrl, blob, aspectRatio };
  } catch {
    return null;
  }
}
