export async function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result as string);
    reader.readAsDataURL(blob);
  });
}

export async function blobToArrayBuffer(blob: Blob): Promise<ArrayBuffer> {
  return blob.arrayBuffer();
}

export async function fetchImageAsBlob(url: string): Promise<Blob> {
  const response = await fetch(url, { credentials: "same-origin" });
  return response.blob();
}

/** Measure a PNG/JPEG/SVG by loading it in an <img>. Returns height/width. */
export async function measureImageAspect(dataUrl: string): Promise<number> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const w = img.naturalWidth || img.width;
      const h = img.naturalHeight || img.height;
      resolve(w > 0 ? h / w : 0.55);
    };
    img.onerror = () => resolve(0.55);
    img.src = dataUrl;
  });
}
