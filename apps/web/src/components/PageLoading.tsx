import { Skeleton } from "@/components/ui";

/** Full-page placeholder: skeleton blocks plus a status text for assistive technology. */
export function PageLoading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-6" role="status">
      <span className="sr-only">{label}</span>
      <Skeleton className="h-7 w-56" />
      <Skeleton className="h-40 w-full rounded-2xl" />
      <div className="grid gap-3 sm:grid-cols-3">
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </div>
    </div>
  );
}
