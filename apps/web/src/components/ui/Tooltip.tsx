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
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom";
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
            "pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 animate-fade-in whitespace-nowrap rounded-md bg-neutral-900 px-2 py-1 text-xs text-white shadow-md dark:bg-neutral-100 dark:text-neutral-900",
            side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
          )}
        >
          {content}
        </span>
      )}
    </span>
  );
}
