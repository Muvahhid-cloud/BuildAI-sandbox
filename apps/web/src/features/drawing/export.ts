// Drawing downloads (docs/3d-engine.md §19.5). The sheets come from the pure engine
// (engine/drawing/sheet.ts); this module only turns their SVG into files in the browser.
// jsPDF and svg2pdf.js are loaded on demand, so the editor bundle does not carry them.
import type { PlanSheet } from "@/engine/drawing/sheet";
import { A3 } from "@/engine/drawing/sheet";

/** PNG resolution: 150 dpi keeps an A3 sheet readable when zoomed and under ~1 MB. */
export const PNG_DPI = 150;

export function drawingFileName(projectName: string, part: string, ext: string): string {
  const slug = (s: string) =>
    s
      .normalize("NFC")
      // Letters of any script stay as written (Cyrillic, Kazakh, accents); punctuation goes.
      .replace(/[^\p{L}\p{M}\p{N}\s_-]/gu, "")
      .replace(/[\s_-]+/g, "-")
      .replace(/^-|-$/g, "")
      .toLowerCase() || "drawing";
  return `${slug(projectName)}-${slug(part)}.${ext}`;
}

function save(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Give the browser a moment to start the download before the URL is revoked.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadSvg(sheet: PlanSheet, fileName: string): void {
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n${sheet.svg}`;
  save(new Blob([xml], { type: "image/svg+xml;charset=utf-8" }), fileName);
}

export async function sheetToPng(sheet: PlanSheet, dpi = PNG_DPI): Promise<Blob> {
  const width = Math.round((A3.width / 25.4) * dpi);
  const height = Math.round((A3.height / 25.4) * dpi);
  const url = URL.createObjectURL(new Blob([sheet.svg], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const image = new Image();
    image.width = width;
    image.height = height;
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("The drawing could not be rasterized"));
      image.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas is not available");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(image, 0, 0, width, height);
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error("PNG encoding failed"))),
        "image/png",
      ),
    );
  } finally {
    URL.revokeObjectURL(url);
  }
}

export async function downloadPng(sheet: PlanSheet, fileName: string): Promise<void> {
  save(await sheetToPng(sheet), fileName);
}

/** One A3 landscape page per sheet, vector (text stays text, lines stay lines). */
export async function sheetsToPdf(sheets: readonly PlanSheet[], title: string): Promise<Blob> {
  const [{ jsPDF }, { svg2pdf }] = await Promise.all([import("jspdf"), import("svg2pdf.js")]);
  const doc = new jsPDF({ orientation: "landscape", unit: "mm", format: "a3", compress: true });
  doc.setProperties({ title, creator: "BuildAI 3D", subject: "Conceptual floor plans" });
  const parser = new DOMParser();
  for (const [i, sheet] of sheets.entries()) {
    if (i > 0) doc.addPage("a3", "landscape");
    const svg = parser.parseFromString(sheet.svg, "image/svg+xml").documentElement;
    // svg2pdf measures text with the live DOM, so the element is attached while it draws.
    const host = document.createElement("div");
    host.style.cssText = "position:fixed;left:-10000px;top:0;width:0;height:0;overflow:hidden";
    host.appendChild(svg);
    document.body.appendChild(host);
    try {
      await svg2pdf(svg, doc, { x: 0, y: 0, width: A3.width, height: A3.height });
    } finally {
      host.remove();
    }
  }
  return doc.output("blob");
}

export async function downloadPdf(
  sheets: readonly PlanSheet[],
  title: string,
  fileName: string,
): Promise<void> {
  save(await sheetsToPdf(sheets, title), fileName);
}
