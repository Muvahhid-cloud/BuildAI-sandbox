import { create } from "zustand";

import type { Layer } from "@/engine/model/types";
import { ALL_LAYERS_VISIBLE } from "@/engine/scene/layers";

interface LayerState {
  visible: Readonly<Record<Layer, boolean>>;
  toggle: (layer: Layer) => void;
  setVisible: (layer: Layer, visible: boolean) => void;
  showAll: () => void;
}

export const useLayerStore = create<LayerState>()((set) => ({
  visible: ALL_LAYERS_VISIBLE,
  toggle: (layer) => set((s) => ({ visible: { ...s.visible, [layer]: !s.visible[layer] } })),
  setVisible: (layer, visible) => set((s) => ({ visible: { ...s.visible, [layer]: visible } })),
  showAll: () => set({ visible: ALL_LAYERS_VISIBLE }),
}));
