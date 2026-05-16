import logoSvgUrl from "@/assets/light_theme_GigaAgent_black-ball.svg";
import { blobToDataUrl } from "../utils";

export const LOGO_CONTENT_VIEWBOX = "200 1250 5000 560";
export const LOGO_ASPECT = 5000 / 560;

let _logoPngCache: { blob: Blob; dataUrl: string } | null = null;

export async function fetchLogoPng(): Promise<{ blob: Blob; dataUrl: string }> {
  if (_logoPngCache) return _logoPngCache;

  const res = await fetch(logoSvgUrl);
  let svgText = await res.text();

  svgText = svgText
    .replace(/viewBox="[^"]*"/, `viewBox="${LOGO_CONTENT_VIEWBOX}"`)
    .replace(/width="[^"]*"/, `width="5000"`)
    .replace(/height="[^"]*"/, `height="560"`);

  const width = 1000;
  const height = Math.round(width / LOGO_ASPECT);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d")!;

  const svgBlob = new Blob([svgText], {
    type: "image/svg+xml;charset=utf-8",
  });
  const objectUrl = URL.createObjectURL(svgBlob);

  const blob = await new Promise<Blob>((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      ctx.drawImage(img, 0, 0, width, height);
      URL.revokeObjectURL(objectUrl);
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error("toBlob failed"))),
        "image/png",
      );
    };
    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("Failed to load SVG"));
    };
    img.src = objectUrl;
  });

  const dataUrl = await blobToDataUrl(blob);
  _logoPngCache = { blob, dataUrl };
  return _logoPngCache;
}
