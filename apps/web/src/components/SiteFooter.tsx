import { Info } from "lucide-react";

import { DISCLAIMER } from "@/lib/disclaimer";

/** The single-source disclaimer stays visible on every page (CLAUDE.md rule 18). */
export function SiteFooter() {
  return (
    <footer className="flex shrink-0 items-start gap-2 border-t border-line bg-bg-subtle px-4 py-2 text-xs leading-snug text-fg-subtle">
      <Info size={13} aria-hidden className="mt-0.5 shrink-0" />
      <p>{DISCLAIMER}</p>
    </footer>
  );
}
