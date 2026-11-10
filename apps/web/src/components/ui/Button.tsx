import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger";
export type ButtonSize = "xs" | "sm" | "md" | "lg";

const BASE =
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap font-medium " +
  "transition-[background-color,border-color,color,box-shadow,transform] duration-150 " +
  "active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-fg shadow-xs hover:bg-accent-hover",
  secondary:
    "bg-neutral-100 text-fg hover:bg-neutral-200 dark:bg-neutral-800 dark:hover:bg-neutral-700",
  outline: "border border-line-strong bg-surface text-fg shadow-xs hover:bg-bg-subtle",
  ghost: "text-fg-muted hover:bg-neutral-100 hover:text-fg dark:hover:bg-neutral-800",
  danger: "bg-red-600 text-white shadow-xs hover:bg-red-700",
};

const SIZE: Record<ButtonSize, string> = {
  xs: "h-6 rounded-sm px-2 text-xs",
  sm: "h-7 rounded-md px-2.5 text-xs",
  md: "h-8 rounded-md px-3 text-sm",
  lg: "h-10 rounded-lg px-4 text-sm",
};

export function buttonClass(
  variant: ButtonVariant = "secondary",
  size: ButtonSize = "md",
  className?: string,
): string {
  return cn(BASE, VARIANT[variant], SIZE[size], className);
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Icon before the label (decorative). */
  icon?: ReactNode;
  /** Shows a spinner and disables the button; the label stays (accessible name unchanged). */
  loading?: boolean;
}

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  loading = false,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={buttonClass(variant, size, className)}
      {...rest}
    >
      {loading ? <Spinner /> : icon ? <span aria-hidden>{icon}</span> : null}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent",
        className,
      )}
    />
  );
}
