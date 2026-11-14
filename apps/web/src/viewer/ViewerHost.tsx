"use client";

import {
  createContext,
  type ReactNode,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import type { SceneGraph } from "@/engine/scene/build-scene";
import { useBuildingStore } from "@/stores/building-store";

import { BuildingViewer } from "./BuildingViewer";

const HostContext = createContext<HTMLElement | null>(null);

/**
 * One 3D canvas for a whole screen. The viewer is rendered once, into an element of its own,
 * and `ViewerSlot` moves that element to wherever the layout currently shows the 3D view — the
 * live-creation stage while a design is made, the editor's viewport once it is saved. The
 * WebGL context, the camera and everything on screen survive the change of layout: no reload,
 * no flash. The viewer shows the building store's scene (none yet: the empty site).
 */
export function ViewerHost({ children }: { children: ReactNode }) {
  const [node] = useState<HTMLElement | null>(() => {
    if (typeof document === "undefined") return null;
    const el = document.createElement("div");
    el.className = "h-full w-full";
    return el;
  });
  const scene = useBuildingStore((s) => s.scene);
  return (
    <HostContext.Provider value={node}>
      {children}
      {node && createPortal(<BuildingViewer scene={scene} />, node)}
    </HostContext.Provider>
  );
}

/**
 * Where the 3D view is shown. Inside a `ViewerHost` it borrows the host's canvas; without one
 * (the demo editor) it renders a viewer of its own for `scene`.
 */
export function ViewerSlot({ scene }: { scene: SceneGraph | null }) {
  const node = useContext(HostContext);
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const slot = ref.current;
    if (!node || !slot) return;
    slot.appendChild(node);
    return () => {
      if (node.parentNode === slot) slot.removeChild(node);
    };
  }, [node]);
  if (!node) return <BuildingViewer scene={scene} />;
  return <div ref={ref} className="h-full w-full" />;
}
