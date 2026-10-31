"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api/errors";
import { refreshSession } from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth-store";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Don't retry client errors (4xx); retry transient failures twice.
        retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
      },
    },
  });
}

/** On first load, try to restore the session from the httpOnly refresh cookie. */
function AuthBootstrap() {
  useEffect(() => {
    if (useAuthStore.getState().status === "unknown") void refreshSession();
  }, []);
  return null;
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <AuthBootstrap />
      {children}
    </QueryClientProvider>
  );
}
