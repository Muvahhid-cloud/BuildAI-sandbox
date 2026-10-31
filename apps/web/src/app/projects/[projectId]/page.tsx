"use client";

import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback } from "react";

import { RequireAuth } from "@/features/auth/components/RequireAuth";
import { ProjectEditor } from "@/features/editor/components/ProjectEditor";

function Editor() {
  const { projectId } = useParams<{ projectId: string }>();
  const router = useRouter();
  const pathname = usePathname();
  // ?generation=<id>: follow an AI generation started from the projects dashboard.
  const generationId = useSearchParams().get("generation");
  // Once another version is open, the link must not reopen the generation's (older) version.
  const releaseGeneration = useCallback(
    () => router.replace(pathname, { scroll: false }),
    [router, pathname],
  );
  return (
    <ProjectEditor
      key={projectId}
      projectId={projectId}
      generationId={generationId}
      onGenerationReleased={generationId ? releaseGeneration : undefined}
    />
  );
}

export default function ProjectEditorPage() {
  return (
    <RequireAuth>
      <Suspense fallback={<p className="p-8 text-sm text-neutral-500">Loading…</p>}>
        <Editor />
      </Suspense>
    </RequireAuth>
  );
}
