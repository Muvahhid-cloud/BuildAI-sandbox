"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { z } from "zod";

import { materialCache } from "@/engine/materials/material-cache";
import { apiRequest } from "@/lib/api/client";
import { useBuildingStore } from "@/stores/building-store";
import { useProjectStore } from "@/stores/project-store";
import { useSelectionStore } from "@/stores/selection-store";
import { useViewerStore } from "@/stores/viewer-store";

import { BuildingEditor } from "./BuildingEditor";

/**
 * Loads the hand-authored demo BuildingModel from the API. The raw JSON is validated
 * (generated schema + integrity checks) and turned into geometry by the building store.
 */
export function DemoEditor() {
  const query = useQuery({
    queryKey: ["demo-building-model"],
    // Validation happens once, in the building store (parseBuildingModel).
    queryFn: () => apiRequest("/demo/building-model", z.unknown(), { auth: false }),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const status = useBuildingStore((s) => s.status);
  const scene = useBuildingStore((s) => s.scene);
  const error = useBuildingStore((s) => s.error);

  useEffect(() => {
    if (query.data === undefined) return;
    useBuildingStore.getState().load(query.data);
    const building = useBuildingStore.getState().index?.model.building;
    useProjectStore.getState().setProject({
      id: null,
      name: building?.name ?? "Demo house",
      source: "demo",
      description: building?.description ?? "",
    });
    useSelectionStore.getState().select(null);
    useViewerStore.getState().reset(); // default visibility + exterior camera
  }, [query.data]);

  useEffect(
    () => () => {
      useBuildingStore.getState().clear();
      useProjectStore.getState().setProject(null);
      materialCache.dispose();
    },
    [],
  );

  if (query.isError) {
    return (
      <Message title="Could not load the demo building model" tone="error">
        <p>{query.error.message}</p>
        <button
          type="button"
          onClick={() => query.refetch()}
          className="mt-3 rounded-md bg-neutral-900 px-3 py-1.5 text-sm text-white"
        >
          Retry
        </button>
      </Message>
    );
  }
  if (status === "error") {
    return (
      <Message title="The building model is invalid" tone="error">
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs">{error}</pre>
      </Message>
    );
  }
  if (!scene) return <Message title="Loading the demo house…" />;
  const name = useBuildingStore.getState().index?.model.building.name ?? "Demo house";
  return (
    <BuildingEditor scene={scene} drawing={{ projectName: name, versionLabel: "Demo model" }} />
  );
}

function Message({
  title,
  tone,
  children,
}: {
  title: string;
  tone?: "error";
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div role={tone === "error" ? "alert" : "status"} className="max-w-xl text-sm">
        <p
          className={"mb-1 font-medium " + (tone === "error" ? "text-red-600" : "text-neutral-500")}
        >
          {title}
        </p>
        {children}
      </div>
    </div>
  );
}
