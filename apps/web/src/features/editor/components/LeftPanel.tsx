"use client";

import { useMemo } from "react";

import type { ModelIndex } from "@/engine/model/model-index";
import type { Layer, Room } from "@/engine/model/types";
import { LAYER_DEFINITIONS } from "@/engine/scene/layers";
import { useLayerStore } from "@/stores/layer-store";
import { useProjectStore } from "@/stores/project-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useViewerStore } from "@/stores/viewer-store";

import { PanelSection, SegmentButton, Toggle } from "./panel-ui";

export function LeftPanel({ index, sectionMax }: { index: ModelIndex; sectionMax: number }) {
  return (
    <div className="flex flex-col text-neutral-800 dark:text-neutral-100">
      <ProjectSection index={index} />
      <FloorSection index={index} />
      <LayerSection index={index} />
      <InspectionSection sectionMax={sectionMax} />
      <RoomSection index={index} />
    </div>
  );
}

function ProjectSection({ index }: { index: ModelIndex }) {
  const project = useProjectStore((s) => s.project);
  const counts = useMemo(() => {
    const c = new Map<string, number>();
    for (const el of index.model.elements) c.set(el.type, (c.get(el.type) ?? 0) + 1);
    return c;
  }, [index]);
  return (
    <PanelSection title="Project">
      <p className="font-medium leading-tight">{project?.name ?? index.model.building.name}</p>
      {project?.source === "demo" && (
        <span className="mt-1 inline-block rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
          Demo · hand-authored model
        </span>
      )}
      <dl className="mt-2 grid grid-cols-2 gap-x-2 gap-y-0.5 text-xs text-neutral-500">
        <dt>Floors</dt>
        <dd className="text-right tabular-nums">{index.levels.length}</dd>
        <dt>Elements</dt>
        <dd className="text-right tabular-nums">{index.model.elements.length}</dd>
        <dt>Rooms</dt>
        <dd className="text-right tabular-nums">{counts.get("room") ?? 0}</dd>
        <dt>Walls / openings</dt>
        <dd className="text-right tabular-nums">
          {counts.get("wall") ?? 0} / {(counts.get("door") ?? 0) + (counts.get("window") ?? 0)}
        </dd>
      </dl>
    </PanelSection>
  );
}

function FloorSection({ index }: { index: ModelIndex }) {
  const levelFilter = useViewerStore((s) => s.levelFilter);
  const selectFloor = useViewerStore((s) => s.selectFloor);
  return (
    <PanelSection title="Floors">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Floor isolation">
        <SegmentButton active={levelFilter === "all"} onClick={() => selectFloor("all")}>
          All
        </SegmentButton>
        {index.levels.map((level) => (
          <SegmentButton
            key={level.id}
            active={levelFilter === level.id}
            onClick={() => selectFloor(level.id)}
          >
            {level.name}
          </SegmentButton>
        ))}
      </div>
    </PanelSection>
  );
}

function LayerSection({ index }: { index: ModelIndex }) {
  const visible = useLayerStore((s) => s.visible);
  const toggle = useLayerStore((s) => s.toggle);
  const counts = useMemo(() => {
    const c = new Map<Layer, number>();
    for (const el of index.model.elements) c.set(el.layer, (c.get(el.layer) ?? 0) + 1);
    return c;
  }, [index]);
  const available = LAYER_DEFINITIONS.filter((l) => l.status === "available");
  const planned = LAYER_DEFINITIONS.filter((l) => l.status === "planned");
  return (
    <PanelSection title="Layers">
      {available.map((l) => (
        <Toggle
          key={l.id}
          label={l.label}
          checked={visible[l.id]}
          onChange={() => toggle(l.id)}
          hint={String(counts.get(l.id) ?? 0)}
        />
      ))}
      <p className="mt-2 text-[11px] leading-snug text-neutral-400">
        Planned: {planned.map((l) => `${l.label} (${l.plannedPhase})`).join(", ")}
      </p>
    </PanelSection>
  );
}

function InspectionSection({ sectionMax }: { sectionMax: number }) {
  const showRoof = useViewerStore((s) => s.showRoof);
  const showExteriorWalls = useViewerStore((s) => s.showExteriorWalls);
  const section = useViewerStore((s) => s.section);
  const setShowRoof = useViewerStore((s) => s.setShowRoof);
  const setShowExteriorWalls = useViewerStore((s) => s.setShowExteriorWalls);
  const setSection = useViewerStore((s) => s.setSection);
  const furniture = useLayerStore((s) => s.visible.furniture);
  const setLayer = useLayerStore((s) => s.setVisible);
  return (
    <PanelSection title="Inspection">
      <Toggle label="Roof" checked={showRoof} onChange={setShowRoof} />
      <Toggle label="Exterior walls" checked={showExteriorWalls} onChange={setShowExteriorWalls} />
      <Toggle label="Furniture" checked={furniture} onChange={(v) => setLayer("furniture", v)} />
      <Toggle
        label="Section cut"
        checked={section.enabled}
        onChange={(enabled) => setSection({ enabled })}
        hint={section.enabled ? `${section.height.toFixed(1)} m` : undefined}
      />
      {section.enabled && (
        <input
          type="range"
          aria-label="Section height (m)"
          min={0.1}
          max={sectionMax}
          step={0.1}
          value={section.height}
          onChange={(e) => setSection({ height: Number(e.target.value) })}
          className="mt-1 w-full accent-blue-600"
        />
      )}
    </PanelSection>
  );
}

function RoomSection({ index }: { index: ModelIndex }) {
  const levelFilter = useViewerStore((s) => s.levelFilter);
  const selectedId = useSelectionStore((s) => s.selectedId);
  const select = useSelectionStore((s) => s.select);
  const levels = index.levels.filter((l) => levelFilter === "all" || l.id === levelFilter);
  return (
    <PanelSection title="Rooms">
      {levels.map((level) => {
        const rooms = (index.elementsByLevel.get(level.id) ?? []).filter(
          (e): e is Room => e.type === "room",
        );
        return (
          <div key={level.id} className="mb-2 last:mb-0">
            <p className="mb-0.5 text-[11px] text-neutral-400">{level.name}</p>
            <ul>
              {rooms.map((room) => (
                <li key={room.id}>
                  <button
                    type="button"
                    onClick={() => select(room.id)}
                    className={
                      "flex w-full justify-between rounded px-1.5 py-0.5 text-left text-sm " +
                      (selectedId === room.id
                        ? "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                        : "hover:bg-neutral-100 dark:hover:bg-neutral-800")
                    }
                  >
                    <span>{room.name}</span>
                    <span className="text-xs tabular-nums text-neutral-400">
                      {Number(room.dimensions.area.toFixed(1))} m²
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </PanelSection>
  );
}
