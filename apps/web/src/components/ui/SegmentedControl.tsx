import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * A group of toggle buttons (aria-pressed), e.g. 3D model / Floor plan. `label` names the
 * group. Buttons without `active` are plain actions inside the same visual group.
 */
export function SegmentedControl({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        "inline-flex flex-wrap items-center gap-0.5 rounded-lg bg-neutral-100 p-0.5 dark:bg-neutral-800/80",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Segment({
  active,
  onClick,
  children,
  title,
  disabled,
}: {
  /** Omit for plain action buttons; pass a boolean for toggle buttons. */
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      aria-pressed={active === undefined ? undefined : active}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs font-medium transition-[background-color,color,box-shadow] duration-150 disabled:opacity-50",
        active
          ? "bg-surface text-fg shadow-sm ring-1 ring-black/5 dark:bg-neutral-600 dark:ring-white/10"
          : "text-fg-muted hover:bg-black/5 hover:text-fg dark:hover:bg-white/10",
      )}
    >
      {children}
    </button>
  );
}
