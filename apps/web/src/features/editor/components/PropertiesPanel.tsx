"use client";

import { useMemo } from "react";

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
      <div className="p-4 text-sm text-neutral-500">
        <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider">Properties</h2>
        <p>Click any object in the 3D view — or a room in the list — to inspect it.</p>
        <p className="mt-3 text-xs">
          Every value shown comes from the building model: wall, room, door, window, slab, stair,
          roof, railing and furniture objects.
        </p>
      </div>
    );
  }

  return (
    <div className="text-sm text-neutral-800 dark:text-neutral-100" aria-label="Properties">
      <header className="flex items-start justify-between gap-2 border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
        <div>
          <h2 className="text-base font-semibold leading-tight">{description.title}</h2>
          <p className="text-xs text-neutral-500">{description.typeLabel}</p>
        </div>
        <button
          type="button"
          onClick={() => select(null)}
          className="rounded px-1.5 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700 dark:hover:bg-neutral-800"
          aria-label="Clear selection"
          title="Clear selection (Esc)"
        >
          ×
        </button>
      </header>
      {element && <ElementEditSection element={element} index={index} />}
      {description.sections.map((section) => (
        <section
          key={section.title}
          className="border-b border-neutral-100 px-4 py-2.5 dark:border-neutral-800"
        >
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
            {section.title}
          </h3>
          {section.rows.length === 0 ? (
            <p className="text-xs text-neutral-400">None</p>
          ) : (
            <dl className="grid grid-cols-[minmax(0,110px)_1fr] gap-x-2 gap-y-1">
              {section.rows.map((row, i) => (
                <div key={`${row.label}-${i}`} className="contents">
                  <dt className="truncate text-xs text-neutral-500" title={row.label}>
                    {row.label}
                  </dt>
                  <dd
                    className={
                      "min-w-0 break-words text-xs " + (row.mono ? "font-mono text-[11px]" : "")
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
