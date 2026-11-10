import { cn } from "@/lib/cn";

/** Placeholder block while content loads (decorative: pair it with a status text). */
export function Skeleton({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "block animate-shimmer rounded-md bg-[linear-gradient(90deg,var(--color-neutral-100)_25%,var(--color-neutral-200)_37%,var(--color-neutral-100)_63%)] bg-[length:200%_100%] dark:bg-[linear-gradient(90deg,var(--color-neutral-800)_25%,var(--color-neutral-700)_37%,var(--color-neutral-800)_63%)]",
        className,
      )}
    />
  );
}
