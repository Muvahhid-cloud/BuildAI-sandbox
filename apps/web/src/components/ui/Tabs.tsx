import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface TabItem<T extends string> {
  value: T;
  label: string;
  icon?: ReactNode;
}

/** Underlined tabs (role="tablist" / role="tab" with aria-selected). */
export function Tabs<T extends string>({
  label,
  items,
  value,
  onChange,
  className,
}: {
  label: string;
  items: readonly TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className={cn("flex gap-1 border-b border-line px-3", className)}
    >
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          role="tab"
          aria-selected={value === item.value}
          onClick={() => onChange(item.value)}
          className={cn(
            "-mb-px inline-flex items-center gap-1.5 border-b-2 px-2.5 py-2.5 text-sm transition-colors duration-150",
            value === item.value
              ? "border-accent font-medium text-fg"
              : "border-transparent text-fg-subtle hover:text-fg",
          )}
        >
          {item.icon && <span aria-hidden>{item.icon}</span>}
          {item.label}
        </button>
      ))}
    </div>
  );
}
