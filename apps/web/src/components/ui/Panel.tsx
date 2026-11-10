import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

/** A surface with a hairline border: cards, lists, forms. */
export function Card({
  className,
  interactive = false,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-line bg-surface shadow-xs",
        interactive &&
          "transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-line-strong hover:shadow-md",
        className,
      )}
      {...rest}
    />
  );
}

/** A titled block inside a side panel. */
export function PanelSection({
  title,
  children,
  aside,
}: {
  title: string;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section className="border-b border-line px-3 py-3">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-2xs font-semibold uppercase tracking-wider text-fg-subtle">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** Callout for notices, warnings and errors (pass role="alert" / "status" where needed). */
export function Callout({
  tone = "info",
  className,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { tone?: "info" | "success" | "warning" | "danger" }) {
  const tones = {
    info: "border-line bg-bg-subtle text-fg-muted",
    success:
      "border-green-200 bg-green-50 text-green-900 dark:border-green-900 dark:bg-green-950/60 dark:text-green-200",
    warning:
      "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-200",
    danger:
      "border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/60 dark:text-red-200",
  } as const;
  return <div className={cn("rounded-lg border p-3 text-sm", tones[tone], className)} {...rest} />;
}
