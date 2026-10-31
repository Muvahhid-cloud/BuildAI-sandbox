import type { ReactNode } from "react";

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
    <section className="border-b border-neutral-200 px-3 py-3 dark:border-neutral-800">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Toggle({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  hint?: string;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 py-0.5 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 accent-blue-600"
      />
      <span className="flex-1">{label}</span>
      {hint && <span className="text-xs tabular-nums text-neutral-400">{hint}</span>}
    </label>
  );
}

export function SegmentButton({
  active,
  onClick,
  children,
  title,
}: {
  /** Omit for plain action buttons; pass a boolean for toggle buttons. */
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active === undefined ? undefined : active}
      title={title}
      onClick={onClick}
      className={
        "rounded-md px-2.5 py-1 text-xs font-medium transition-colors " +
        (active
          ? "bg-blue-600 text-white"
          : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-200 dark:hover:bg-neutral-700")
      }
    >
      {children}
    </button>
  );
}
