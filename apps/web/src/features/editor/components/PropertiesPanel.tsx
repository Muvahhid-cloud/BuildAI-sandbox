"use client";

import { MousePointerClick, X } from "lucide-react";
import { useMemo } from "react";

import { IconButton } from "@/components/ui";
import type { ModelIndex } from "@/engine/model/model-index";
import { ElementEditSection } from "@/features/editing/components/ElementEditSection";
import { useSelectionStore } from "@/stores/selection-store";

import { describeElement } from "../describe-element";

/** Properties of the selected element, generated from the BuildingModel. */
export function PropertiesPanel({ index }: { index: ModelIndex }) {
  const selectedId = useSelectionStore((s) => s.selectedId);
  const select = useSelectionStore((s) => s.select);
  const element = selectedId ? index.elementsById.get(selectedId) : undefined;
  const description = useMemo(
    () => (element ? describeElement(element, index) : null),
    [element, index],
  );

  if (!description) {
    return (
      <div className="flex flex-col items-center gap-2 px-5 py-10 text-center text-sm text-fg-subtle">
        <span
          aria-hidden
          className="mb-1 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-neutral-100 text-fg-subtle dark:bg-neutral-800"
        >
          <MousePointerClick size={18} />
        </span>
        <h2 className="text-2xs font-semibold uppercase tracking-wider">Properties</h2>
        <p className="text-fg-muted">
          Click any object in the 3D view — or a room in the list — to inspect it.
        </p>
        <p className="text-xs">
          Every value shown comes from the building model: wall, room, door, window, slab, stair,
          roof, railing and furniture objects.
        </p>
      </div>
    );
  }

  return (
    <div className="text-sm text-fg" aria-label="Properties">
      <header className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
        <div>
          <h2 className="text-[15px] font-semibold leading-tight tracking-tight">
            {description.title}
          </h2>
          <p className="text-xs text-fg-subtle">{description.typeLabel}</p>
        </div>
        <IconButton
          label="Clear selection"
          title="Clear selection (Esc)"
          size="sm"
          onClick={() => select(null)}
        >
          <X size={14} />
        </IconButton>
      </header>
      {element && <ElementEditSection element={element} index={index} />}
      {description.sections.map((section) => (
        <section key={section.title} className="border-b border-line px-4 py-3">
          <h3 className="mb-1 text-2xs font-semibold uppercase tracking-wider text-fg-subtle">
            {section.title}
          </h3>
          {section.rows.length === 0 ? (
            <p className="text-xs text-fg-subtle">None</p>
          ) : (
            <dl className="grid grid-cols-[minmax(0,112px)_1fr] gap-x-3 gap-y-1.5">
              {section.rows.map((row, i) => (
                <div key={`${row.label}-${i}`} className="contents">
                  <dt className="truncate text-xs text-fg-subtle" title={row.label}>
                    {row.label}
                  </dt>
                  <dd
                    className={
                      "min-w-0 break-words text-xs font-medium tabular-nums " +
                      (row.mono ? "font-mono text-2xs font-normal" : "")
                    }
                  >
                    {row.targetId ? (
                      <button
                        type="button"
                        onClick={() => select(row.targetId!)}
                        className="text-left text-blue-700 hover:underline dark:text-blue-400"
                      >
                        {row.value}
                      </button>
                    ) : (
                      row.value
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      ))}
    </div>
  );
}
