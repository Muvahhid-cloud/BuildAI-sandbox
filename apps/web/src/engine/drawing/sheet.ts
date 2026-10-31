// A3 drawing sheet (landscape) for one level: frame, title, plan at a standard scale, north
// arrow, scale bar, title block and the disclaimer (docs/3d-engine.md §19.4). Pure: the
// caller passes everything that is not in the model (project name, version, date, text).
import type { ModelIndex } from "../model/model-index";
import { roomsOf } from "../model/model-index";
import { buildPlanDrawing, formatArea, type PlanOptions } from "./plan";
import { textWidthMm } from "./plan-math";
import type { PlanDrawing } from "./primitives";
import { escapeXml, FONT_FAMILY, fmt, paperBox, renderPlanContent } from "./svg";

export const A3 = { width: 420, height: 297 } as const;

/** Standard plan scales tried in order; the first at which the plan fits is used. */
export const PLAN_SCALES = [100, 200, 250, 500] as const;

const FRAME = { left: 20, top: 5, right: 5, bottom: 5 };
const TITLE_BLOCK = { width: 185, height: 40 };
const PAD = 8;
const TITLE_H = 10;

const OUTDOOR = new Set(["terrace", "balcony"]);

export interface SheetInfo {
  projectName: string;
  /** e.g. "v3 · AI generation". */
  versionLabel: string;
  /** ISO date printed in the title block (passed in: the engine never reads the clock). */
  date: string;
  sheetNumber: number;
  sheetCount: number;
  disclaimer: string;
}

export interface PlanSheet {
  levelId: string;
  title: string;
  scale: number;
  drawing: PlanDrawing;
  svg: string;
}

/** The area available to the plan, in sheet mm. */
export function planArea() {
  const x0 = FRAME.left + PAD;
  const x1 = A3.width - FRAME.right - PAD;
  const y0 = FRAME.top + PAD + TITLE_H;
  const y1 = A3.height - FRAME.bottom - TITLE_BLOCK.height - PAD;
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
}

export function planTitle(levelName: string): string {
  return `${levelName} plan`;
}

/** Builds the plan at the largest standard scale at which it fits the sheet. */
export function fitPlan(
  index: ModelIndex,
  levelId: string,
  options: Omit<PlanOptions, "scale"> = {},
): PlanDrawing {
  const area = planArea();
  let drawing: PlanDrawing | null = null;
  for (const scale of PLAN_SCALES) {
    drawing = buildPlanDrawing(index, levelId, { ...options, scale });
    const box = paperBox(drawing.bounds, scale);
    if (box.width <= area.width && box.height <= area.height) return drawing;
  }
  return drawing!;
}

export function buildPlanSheet(
  index: ModelIndex,
  levelId: string,
  info: SheetInfo,
  options: Omit<PlanOptions, "scale"> = {},
): PlanSheet {
  const drawing = fitPlan(index, levelId, options);
  const title = planTitle(drawing.levelName);
  const area = planArea();
  const box = paperBox(drawing.bounds, drawing.scale);
  // Center the plan in its area.
  const tx = area.x + (area.width - box.width) / 2 - box.x;
  const ty = area.y + (area.height - box.height) / 2 - box.y;
  const indoor = roomsOf(index, levelId)
    .filter((r) => !OUTDOOR.has(r.properties.room_type))
    .reduce((sum, r) => sum + r.dimensions.area, 0);

  const parts: string[] = [];
  parts.push(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${A3.width}mm" height="${A3.height}mm" viewBox="0 0 ${A3.width} ${A3.height}">`,
  );
  parts.push(`<rect x="0" y="0" width="${A3.width}" height="${A3.height}" fill="#ffffff"/>`);
  // Frame.
  const fw = A3.width - FRAME.left - FRAME.right;
  const fh = A3.height - FRAME.top - FRAME.bottom;
  parts.push(rectSvg(FRAME.left, FRAME.top, fw, fh, 0.5));
  // Drawing title, underlined, with the scale.
  parts.push(
    text(
      area.x + area.width / 2,
      FRAME.top + PAD + 5,
      `${title.toUpperCase()}  1:${drawing.scale}`,
      5,
      "middle",
      true,
    ),
  );
  // Plan.
  parts.push(`<g transform="translate(${fmt(tx)} ${fmt(ty)})">${renderPlanContent(drawing)}</g>`);
  // Bottom strip, left of the title block: north arrow, scale bar, disclaimer.
  const stripY = A3.height - FRAME.bottom - TITLE_BLOCK.height;
  parts.push(northArrow(FRAME.left + 14, stripY + 15));
  parts.push(scaleBar(FRAME.left + 32, stripY + 17, drawing.scale));
  const stripW = A3.width - FRAME.right - TITLE_BLOCK.width - FRAME.left - 8;
  wrap(info.disclaimer, 1.9, stripW).forEach((lineText, i) =>
    parts.push(text(FRAME.left + 4, stripY + 31 + i * 2.6, lineText, 1.9, "start")),
  );
  parts.push(
    titleBlock(A3.width - FRAME.right - TITLE_BLOCK.width, stripY, {
      ...info,
      title,
      scale: drawing.scale,
      indoorArea: `${formatArea(indoor)} m²`,
    }),
  );
  parts.push(`</svg>`);
  return { levelId, title, scale: drawing.scale, drawing, svg: parts.join("") };
}

export function buildPlanSheets(
  index: ModelIndex,
  info: Omit<SheetInfo, "sheetNumber" | "sheetCount">,
  options: Omit<PlanOptions, "scale"> = {},
): PlanSheet[] {
  const levels = index.levels;
  return levels.map((level, i) =>
    buildPlanSheet(
      index,
      level.id,
      { ...info, sheetNumber: i + 1, sheetCount: levels.length },
      options,
    ),
  );
}

// ---------------------------------------------------------------- pieces

function rectSvg(x: number, y: number, w: number, h: number, stroke: number): string {
  return `<rect x="${fmt(x)}" y="${fmt(y)}" width="${fmt(w)}" height="${fmt(h)}" fill="none" stroke="#000000" stroke-width="${stroke}"/>`;
}

function lineSvg(x0: number, y0: number, x1: number, y1: number, stroke: number): string {
  return `<line x1="${fmt(x0)}" y1="${fmt(y0)}" x2="${fmt(x1)}" y2="${fmt(y1)}" stroke="#000000" stroke-width="${stroke}"/>`;
}

function text(
  x: number,
  y: number,
  value: string,
  size: number,
  anchor: "start" | "middle" | "end",
  bold = false,
): string {
  return (
    `<text x="${fmt(x)}" y="${fmt(y)}" font-family="${FONT_FAMILY}" font-size="${fmt(size)}"` +
    `${bold ? ' font-weight="bold"' : ""} text-anchor="${anchor}" fill="#000000">${escapeXml(value)}</text>`
  );
}

/** Greedy word wrap by estimated width (deterministic). */
export function wrap(value: string, size: number, widthMm: number): string[] {
  const lines: string[] = [];
  let current = "";
  for (const word of value.split(/\s+/)) {
    const next = current ? `${current} ${word}` : word;
    if (current && textWidthMm(next, size) > widthMm) {
      lines.push(current);
      current = word;
    } else current = next;
  }
  if (current) lines.push(current);
  return lines;
}

function northArrow(cx: number, cy: number): string {
  const r = 7;
  return (
    `<circle cx="${fmt(cx)}" cy="${fmt(cy)}" r="${r}" fill="none" stroke="#000000" stroke-width="0.25"/>` +
    `<polygon points="${fmt(cx)},${fmt(cy - r)} ${fmt(cx + 2.2)},${fmt(cy + r * 0.6)} ${fmt(cx)},${fmt(cy + r * 0.25)}" fill="#000000"/>` +
    `<polygon points="${fmt(cx)},${fmt(cy - r)} ${fmt(cx - 2.2)},${fmt(cy + r * 0.6)} ${fmt(cx)},${fmt(cy + r * 0.25)}" fill="#ffffff" stroke="#000000" stroke-width="0.2"/>` +
    text(cx, cy - r - 1.5, "N", 3.5, "middle", true)
  );
}

/** Alternating scale bar 0–5 m (0–10 m at 1:200 and smaller). */
function scaleBar(x: number, y: number, scale: number): string {
  const meters = scale <= 100 ? 5 : scale <= 250 ? 10 : 20;
  const mm = (meters * 1000) / scale;
  const steps = 5;
  const step = mm / steps;
  const parts: string[] = [];
  for (let i = 0; i < steps; i++) {
    parts.push(
      `<rect x="${fmt(x + i * step)}" y="${fmt(y)}" width="${fmt(step)}" height="1.5" fill="${i % 2 === 0 ? "#000000" : "#ffffff"}" stroke="#000000" stroke-width="0.2"/>`,
    );
  }
  for (let i = 0; i <= steps; i++) {
    parts.push(text(x + i * step, y - 1.2, fmt((meters * i) / steps), 2.2, "middle"));
  }
  parts.push(text(x + mm + 3, y + 1.5, "m", 2.2, "start"));
  return parts.join("");
}

function titleBlock(
  x: number,
  y: number,
  info: SheetInfo & { title: string; scale: number; indoorArea: string },
): string {
  const w = TITLE_BLOCK.width;
  const h = TITLE_BLOCK.height;
  const row = h / 4;
  const c1 = x + 120;
  const c2 = x + 152;
  const parts = [rectSvg(x, y, w, h, 0.5)];
  for (let i = 1; i < 4; i++) parts.push(lineSvg(x, y + i * row, x + w, y + i * row, 0.25));
  parts.push(lineSvg(c1, y + row, c1, y + h, 0.25));
  parts.push(lineSvg(c2, y + 3 * row, c2, y + h, 0.25));
  const label = (lx: number, ly: number, v: string) => text(lx + 1.5, ly + 3, v, 1.8, "start");
  const value = (lx: number, ly: number, v: string, size = 3) =>
    text(lx + 1.5, ly + row - 2, v, size, "start", true);
  parts.push(
    text(
      x + w / 2,
      y + row / 2 + 1.5,
      "CONCEPTUAL DESIGN — NOT FOR CONSTRUCTION",
      3.2,
      "middle",
      true,
    ),
  );
  parts.push(label(x, y + row, "Project"), value(x, y + row, clip(info.projectName, 3, 116)));
  parts.push(
    label(c1, y + row, "Version"),
    value(c1, y + row, clip(info.versionLabel, 2.4, 62), 2.4),
  );
  parts.push(label(x, y + 2 * row, "Drawing"), value(x, y + 2 * row, info.title));
  parts.push(label(c1, y + 2 * row, "Scale"), value(c1, y + 2 * row, `1:${info.scale}`));
  parts.push(
    label(x, y + 3 * row, "Indoor room area · BuildAI 3D"),
    value(x, y + 3 * row, info.indoorArea),
  );
  parts.push(label(c1, y + 3 * row, "Date"), value(c1, y + 3 * row, info.date, 2.4));
  parts.push(
    label(c2, y + 3 * row, "Sheet"),
    value(c2, y + 3 * row, `${info.sheetNumber} / ${info.sheetCount}`),
  );
  return parts.join("");
}

function clip(value: string, size: number, widthMm: number): string {
  if (textWidthMm(value, size) <= widthMm) return value;
  let out = value;
  while (out.length > 1 && textWidthMm(`${out}…`, size) > widthMm) out = out.slice(0, -1);
  return `${out}…`;
}
