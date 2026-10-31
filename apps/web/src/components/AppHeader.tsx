"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { logout } from "@/features/auth/api";
import { useAuthStore } from "@/stores/auth-store";

export function AppHeader() {
  const user = useAuthStore((s) => s.user);
  const router = useRouter();
  const queryClient = useQueryClient();

  async function onLogout() {
    await logout().catch(() => undefined);
    queryClient.clear();
    router.replace("/login");
  }

  return (
    <header className="flex items-center gap-4 border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
      <Link href="/" className="font-semibold tracking-tight">
        BuildAI 3D
      </Link>
      {!user && (
        <nav className="ml-auto flex items-center gap-4 text-sm">
          <Link href="/projects" className="hover:underline">
            Projects
          </Link>
          <Link href="/login" className="hover:underline">
            Sign in
          </Link>
        </nav>
      )}
      {user && (
        <nav className="ml-auto flex items-center gap-4 text-sm">
          <Link href="/projects" className="hover:underline">
            Projects
          </Link>
          <span className="text-neutral-500">{user.display_name}</span>
          <button type="button" onClick={onLogout} className="text-neutral-500 hover:underline">
            Sign out
          </button>
        </nav>
      )}
    </header>
  );
}
