import { DISCLAIMER } from "@/lib/disclaimer";

export function SiteFooter() {
  return (
    <footer className="border-t border-neutral-200 px-4 py-3 text-xs text-neutral-500 dark:border-neutral-800">
      {DISCLAIMER}
    </footer>
  );
}
