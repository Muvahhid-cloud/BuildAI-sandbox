// PlanDrawing -> SVG markup. One renderer for the on-screen plan and every export (SVG, PNG,
// PDF), so they always match. Output units are PAPER millimeters at the drawing scale; the
// model's +Y (north) points up the sheet. Only presentation attributes are used (no CSS
// classes), so the markup renders the same in browsers, image conversion and svg2pdf.
import type { P2 } from "../math/polygon";
import type { Bounds, DrawItem, Fill, Pen, PlanDrawing, TextRole } from "./primitives";

interface PenStyle {
  width: number;
  color: string;
  dash?: string;
}

/** Line weights (paper mm) following the usual 1:100 plan hierarchy. */
export const PENS: Record<Exclude<Pen, "none">, PenStyle> = {
  cut: { width: 0.1, color: "#000000" },
  outline: { width: 0.35, color: "#000000" },
  thin: { width: 0.25, color: "#000000" },
  fine: { width: 0.13, color: "#000000" },
  hidden: { width: 0.18, color: "#000000", dash: "1.5 1" },
  hatch: { width: 0.1, color: "#8c8c8c" },
  furniture: { width: 0.18, color: "#5a5a5a" },
  dim: { width: 0.13, color: "#000000" },
};

const FILLS: Record<Exclude<Fill, "none" | "hit">, string> = {
  solid: "#000000",
  paper: "#ffffff",
};

const TEXT_COLOR: Record<TextRole, string> = {
  room: "#000000",
  area: "#333333",
  dim: "#000000",
  note: "#333333",
};

export const FONT_FAMILY = "Helvetica, Arial, sans-serif";

export interface SvgPlanOptions {
  /** Interactive view: element ids, pointer targets and data attributes for highlighting. */
  interactive?: boolean;
}

/** Number formatting: 0.01 mm resolution, no "-0", no trailing zeros. */
export function fmt(n: number): string {
  const r = Math.round(n * 100) / 100;
  return Object.is(r, -0) ? "0" : String(r);
}

export function escapeXml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Model meters -> paper mm for a drawing scale, with model (0, 0) at paper (0, 0). */
export function paperPoint([x, y]: P2, scale: number): P2 {
  const m = 1000 / scale;
  return [x * m, -y * m];
}

/** Paper-mm box of model bounds, plus a margin. */
export function paperBox(b: Bounds, scale: number, margin = 0) {
  const [x0, y0] = paperPoint([b.minX, b.maxY], scale);
  const [x1, y1] = paperPoint([b.maxX, b.minY], scale);
  return {
    x: x0 - margin,
    y: y0 - margin,
    width: x1 - x0 + 2 * margin,
    height: y1 - y0 + 2 * margin,
  };
}

function strokeAttrs(pen: Pen): string {
  if (pen === "none") return ' stroke="none"';
  const s = PENS[pen];
  return (
    ` stroke="${s.color}" stroke-width="${s.width}" stroke-linejoin="miter" stroke-linecap="butt"` +
    (s.dash ? ` stroke-dasharray="${s.dash}"` : "")
  );
}

function fillAttr(fill: Fill, interactive: boolean): string | null {
  if (fill === "hit") return interactive ? ' fill="#000000" fill-opacity="0"' : null;
  if (fill === "none") return ' fill="none"';
  return ` fill="${FILLS[fill]}"`;
}

function itemSvg(item: DrawItem, scale: number, interactive: boolean): string {
  const data = (fill: Fill) => (interactive && fill !== "none" ? ` data-fill="${fill}"` : "");
  switch (item.kind) {
    case "poly": {
      const fill = fillAttr(item.fill, interactive);
      if (fill === null) return "";
      const pts = item.pts
        .map((p) => paperPoint(p, scale))
        .map(([x, y]) => `${fmt(x)},${fmt(y)}`)
        .join(" ");
      const tag = item.closed ? "polygon" : "polyline";
      const fillOut = item.closed ? fill : ' fill="none"';
      return `<${tag} points="${pts}"${fillOut}${strokeAttrs(item.pen)}${data(item.fill)}/>`;
    }
    case "circle": {
      const fill = fillAttr(item.fill, interactive);
      if (fill === null) return "";
      const [x, y] = paperPoint(item.center, scale);
      return `<circle cx="${fmt(x)}" cy="${fmt(y)}" r="${fmt((item.r * 1000) / scale)}"${fill}${strokeAttrs(item.pen)}/>`;
    }
    case "text": {
      const [x, y] = paperPoint(item.at, scale);
      const deg = (item.angle * 180) / Math.PI;
      const rotate =
        Math.abs(deg) > 1e-9 ? ` transform="rotate(${fmt(-deg)} ${fmt(x)} ${fmt(y)})"` : "";
      const weight = item.role === "room" ? ' font-weight="bold"' : "";
      return (
        `<text x="${fmt(x)}" y="${fmt(y)}" font-family="${FONT_FAMILY}" font-size="${fmt(item.size)}"` +
        `${weight} text-anchor="${item.anchor}" fill="${TEXT_COLOR[item.role]}"${rotate}>` +
        `${escapeXml(item.text)}</text>`
      );
    }
  }
}

/** The drawing's groups as SVG markup (no outer <svg>), model (0,0) at paper (0,0). */
export function renderPlanContent(drawing: PlanDrawing, options: SvgPlanOptions = {}): string {
  const interactive = options.interactive ?? false;
  const out: string[] = [];
  for (const g of drawing.groups) {
    const body = g.items.map((it) => itemSvg(it, drawing.scale, interactive)).join("");
    if (!body) continue;
    const attrs =
      (interactive && g.elementId ? ` data-element-id="${g.elementId}"` : "") +
      (interactive ? ` data-role="${g.role}"` : "");
    out.push(`<g${attrs}>${body}</g>`);
  }
  return out.join("");
}

/** A standalone SVG of the plan alone (no sheet), sized in mm. */
export function renderPlanSvg(drawing: PlanDrawing, marginMm = 10): string {
  const box = paperBox(drawing.bounds, drawing.scale, marginMm);
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${fmt(box.width)}mm" height="${fmt(box.height)}mm" ` +
    `viewBox="${fmt(box.x)} ${fmt(box.y)} ${fmt(box.width)} ${fmt(box.height)}">` +
    `<rect x="${fmt(box.x)}" y="${fmt(box.y)}" width="${fmt(box.width)}" height="${fmt(box.height)}" fill="#ffffff"/>` +
    renderPlanContent(drawing) +
    `</svg>`
  );
}
