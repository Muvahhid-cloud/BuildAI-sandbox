"use client";

import { RequireAuth } from "@/features/auth/components/RequireAuth";
import { ProjectsDashboard } from "@/features/projects/components/ProjectsDashboard";

export default function ProjectsPage() {
  return (
    <RequireAuth>
      <ProjectsDashboard />
    </RequireAuth>
  );
}
