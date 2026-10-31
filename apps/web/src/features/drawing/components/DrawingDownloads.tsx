"use client";

import { useState } from "react";

import { buildPlanSheet, buildPlanSheets, type SheetInfo } from "@/engine/drawing/sheet";
import type { ModelIndex } from "@/engine/model/model-index";
import { DISCLAIMER } from "@/lib/disclaimer";
import { useLayerStore } from "@/stores/layer-store";
import { useViewerStore } from "@/stores/viewer-store";

import { downloadPdf, downloadPng, downloadSvg, drawingFileName } from "../export";

export interface DrawingInfo {
  projectName: string;
  versionLabel: string;
}

type Format = "svg" | "png" | "pdf";

/** Today's date for the title block (the drawing engine never reads the clock itself). */
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Downloads of the floor plans as A3 sheets: SVG and PNG of the level on screen, PDF with
 * one page per level. Furniture follows the Furniture layer toggle, as on screen.
 */
export function DrawingDownloads({ index, info }: { index: ModelIndex; info: DrawingInfo }) {
  const planLevelId = useViewerStore((s) => s.planLevelId);
  const furniture = useLayerStore((s) => s.visible.furniture);
  const [busy, setBusy] = useState<Format | null>(null);
  const [error, setError] = useState<string | null>(null);
  const level = index.levels.find((l) => l.id === planLevelId) ?? index.levels[0];

  const run = async (format: Format) => {
    if (!level) return;
    setBusy(format);
    setError(null);
    try {
      const base: Omit<SheetInfo, "sheetNumber" | "sheetCount"> = {
        ...info,
        date: today(),
        disclaimer: DISCLAIMER,
      };
      if (format === "pdf") {
        const sheets = buildPlanSheets(index, base, { furniture });
        await downloadPdf(
          sheets,
          `${info.projectName} — floor plans`,
          drawingFileName(info.projectName, "floor-plans", "pdf"),
        );
        return;
      }
      const number = index.levels.indexOf(level) + 1;
      const sheet = buildPlanSheet(
        index,
        level.id,
        { ...base, sheetNumber: number, sheetCount: index.levels.length },
        { furniture },
      );
      const name = drawingFileName(info.projectName, `${level.name} plan`, format);
      if (format === "svg") downloadSvg(sheet, name);
      else await downloadPng(sheet, name);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const button = (format: Format, label: string, title: string) => (
    <button
      type="button"
      onClick={() => void run(format)}
      disabled={busy !== null}
      title={title}
      className="rounded-md bg-neutral-100 px-2.5 py-1 text-xs font-medium text-neutral-700 hover:bg-neutral-200 disabled:opacity-50 dark:bg-neutral-800 dark:text-neutral-200 dark:hover:bg-neutral-700"
    >
      {busy === format ? "Preparing…" : label}
    </button>
  );

  return (
    <div className="flex items-center gap-1" role="group" aria-label="Download drawing">
      <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
        Download
      </span>
      {button("pdf", "PDF", "A3 sheets, one page per floor (vector)")}
      {button("svg", "SVG", "This floor as an A3 vector sheet")}
      {button("png", "PNG", "This floor as an A3 image (150 dpi)")}
      {error && (
        <span role="alert" className="ml-1 text-xs text-red-600">
          {error}
        </span>
      )}
    </div>
  );
}
