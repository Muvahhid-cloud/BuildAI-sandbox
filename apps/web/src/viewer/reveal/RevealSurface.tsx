"use client";

import { type ReactNode, useEffect, useRef } from "react";

import { Kbd } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useRevealStore } from "@/stores/reveal-store";

import { REVEAL } from "../render-settings";

/**
 * The viewport around the 3D canvas while a design is created or built.
 *
 * - Any interaction ends a running construction at once: the start of a drag, the wheel, a
 *   click, or Esc. The events are only observed (capture phase) — the same pointer-down or
 *   wheel event still reaches the orbit controls, so the camera is the user's from that very
 *   gesture. A click that ended the construction does not also select an element. Skipping
 *   touches the animation only; what the backend reports is shown as it is.
 * - If a stage fails after the house was shown, the canvas fades out; when the fade is over
 *   the machine is idle again and the caller shows the ground (or the previous version).
 */
export function RevealSurface({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const building = useRevealStore((s) => s.phase === "assembling" && s.mode === "build");
  const collapsing = useRevealStore((s) => s.phase === "collapsing");

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let skippedByPress = false;
    const skip = () => {
      const reveal = useRevealStore.getState();
      if (reveal.phase !== "assembling") return false;
      reveal.dispatch({ type: "skip" });
      return true;
    };
    const onPointerDown = () => {
      skippedByPress = skip();
    };
    const onWheel = () => {
      skip();
    };
    const onClick = (event: MouseEvent) => {
      if (skip() || skippedByPress) event.stopPropagation();
      skippedByPress = false;
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") skip();
    };
    el.addEventListener("pointerdown", onPointerDown, true);
    el.addEventListener("wheel", onWheel, { capture: true, passive: true });
    el.addEventListener("click", onClick, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      el.removeEventListener("pointerdown", onPointerDown, true);
      el.removeEventListener("wheel", onWheel, true);
      el.removeEventListener("click", onClick, true);
      window.removeEventListener("keydown", onKey, true);
    };
  }, []);

  // The fade after a failure is the machine's "collapsing" phase; it ends by the clock.
  useEffect(() => {
    if (!collapsing) return;
    const id = window.setTimeout(
      () => useRevealStore.getState().dispatch({ type: "tick", dt: REVEAL.fail.fade }),
      REVEAL.fail.fade * 1000,
    );
    return () => window.clearTimeout(id);
  }, [collapsing]);

  return (
    <div ref={ref} data-reveal-surface className={cn("relative h-full w-full", className)}>
      <div
        className="absolute inset-0 transition-opacity ease-in-out"
        style={{ opacity: collapsing ? 0 : 1, transitionDuration: `${REVEAL.fail.fade}s` }}
      >
        {children}
      </div>
      {building && (
        <div className="pointer-events-none absolute inset-x-0 top-4 z-[5] flex justify-center">
          <span
            role="note"
            className="glass flex animate-fade-in items-center gap-1.5 rounded-full px-3 py-1 text-xs text-fg-muted shadow-md"
          >
            Drag, scroll or <Kbd>Esc</Kbd> to skip the build animation
          </span>
        </div>
      )}
    </div>
  );
}
