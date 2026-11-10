"use client";

import { useId, useState, type ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * A small label shown on hover or keyboard focus. The tooltip text is only in the DOM while it
 * is shown, and it describes (aria-describedby) rather than names the trigger.
 */
export function Tooltip({
  content,
  children,
  side = "top",
  align = "start",
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom";
  /** Which edge of the trigger the tooltip lines up with (keeps it inside the viewport). */
  align?: "start" | "center" | "end";
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      aria-describedby={open ? id : undefined}
    >
      {children}
      {open && (
        <span
          id={id}
          role="tooltip"
          className={cn(
            "pointer-events-none absolute z-50 inline-flex animate-fade-in items-center gap-1.5 whitespace-nowrap rounded-md border border-line bg-surface-raised px-2 py-1 text-xs text-fg shadow-md",
            align === "start"
              ? "left-0"
              : align === "end"
                ? "right-0"
                : "left-1/2 -translate-x-1/2",
            side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
          )}
        >
          {content}
        </span>
      )}
    </span>
  );
}
