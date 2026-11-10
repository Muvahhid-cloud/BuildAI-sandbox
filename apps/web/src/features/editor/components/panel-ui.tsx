// Editor panel pieces, built on the component kit (@/components/ui).
import type { ReactNode } from "react";

import { Segment } from "@/components/ui";

export { PanelSection } from "@/components/ui";

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
    <label className="group flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 text-sm transition-colors hover:bg-neutral-100 dark:hover:bg-neutral-800">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 rounded accent-[var(--accent)]"
      />
      <span className="flex-1">{label}</span>
      {hint && <span className="text-xs tabular-nums text-fg-subtle">{hint}</span>}
    </label>
  );
}

/** A toggle (with `active`) or action button of the editor toolbars. */
export function SegmentButton(props: {
  /** Omit for plain action buttons; pass a boolean for toggle buttons. */
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string;
}) {
  return <Segment {...props} />;
}
