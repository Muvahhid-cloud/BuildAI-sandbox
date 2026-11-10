import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accessible name (required: the button shows only an icon). Pass title="" to drop the native tooltip (when wrapped in <Tooltip>). */
  label: string;
  children: ReactNode;
  size?: "sm" | "md";
  /** Toggle buttons: sets aria-pressed and the active look. */
  pressed?: boolean;
}

export function IconButton({
  label,
  children,
  size = "md",
  pressed,
  className,
  title,
  type = "button",
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      aria-pressed={pressed}
      title={title === "" ? undefined : (title ?? label)}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md text-fg-subtle transition-colors duration-150",
        "hover:bg-neutral-100 hover:text-fg disabled:pointer-events-none disabled:opacity-50 dark:hover:bg-neutral-800",
        size === "sm" ? "h-6 w-6" : "h-8 w-8",
        pressed && "bg-accent-soft text-accent-text hover:bg-accent-soft hover:text-accent-text",
        className,
      )}
      {...rest}
    >
      <span aria-hidden className="inline-flex">
        {children}
      </span>
    </button>
  );
}
