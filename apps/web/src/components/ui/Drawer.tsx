import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

import { IconButton } from "./IconButton";

/** A panel that slides in over the right edge of its (relative) container. */
export function Drawer({
  label,
  children,
  className,
}: {
  /** Accessible name of the complementary region. */
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <aside
      aria-label={label}
      className={cn(
        "absolute inset-y-0 right-0 z-20 flex w-full max-w-[520px] animate-drawer-in flex-col border-l border-line bg-surface shadow-lg",
        className,
      )}
    >
      {children}
    </aside>
  );
}

/** Title row of a drawer or panel, with an optional close button ("Close"). */
export function DrawerHeader({
  title,
  description,
  icon,
  onClose,
  closeLabel = "Close",
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  onClose?: () => void;
  /** Accessible name of the close button. */
  closeLabel?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 border-b border-line px-4 py-3">
      {icon && (
        <span
          aria-hidden
          className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text"
        >
          {icon}
        </span>
      )}
      <div className="min-w-0 flex-1">
        <h2 className="text-[15px] font-semibold leading-snug tracking-tight">{title}</h2>
        {description && <p className="mt-0.5 text-xs text-fg-subtle">{description}</p>}
        {children}
      </div>
      {onClose && (
        <IconButton label={closeLabel} onClick={onClose} size="md" className="-mr-1.5 -mt-0.5">
          <X size={16} />
        </IconButton>
      )}
    </div>
  );
}
