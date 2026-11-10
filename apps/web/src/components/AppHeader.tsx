"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Button, buttonClass, ThemeToggle } from "@/components/ui";
import { logout } from "@/features/auth/api";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/stores/auth-store";

import { Logo } from "./Logo";

export function AppHeader() {
  const user = useAuthStore((s) => s.user);
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();

  async function onLogout() {
    await logout().catch(() => undefined);
    queryClient.clear();
    router.replace("/login");
  }

  const navLink = (href: string, label: string) => (
    <Link
      href={href}
      aria-current={pathname?.startsWith(href) ? "page" : undefined}
      className={cn(
        "rounded-md px-2.5 py-1 text-sm transition-colors duration-150",
        pathname?.startsWith(href)
          ? "bg-neutral-100 font-medium text-fg dark:bg-neutral-800"
          : "text-fg-muted hover:bg-neutral-100 hover:text-fg dark:hover:bg-neutral-800",
      )}
    >
      {label}
    </Link>
  );

  return (
    <header className="z-30 flex h-12 shrink-0 items-center gap-2 border-b border-line bg-surface/90 px-3 backdrop-blur sm:px-4">
      <Link
        href="/"
        className="mr-2 flex items-center gap-2 rounded-md py-1 pr-1.5 text-[15px] font-semibold tracking-tight"
      >
        <Logo />
        BuildAI 3D
      </Link>
      <nav className="ml-auto flex items-center gap-1 text-sm">
        {navLink("/projects", "Projects")}
        {!user && (
          <Link href="/login" className={buttonClass("primary", "sm", "ml-1")}>
            Sign in
          </Link>
        )}
        {user && (
          <>
            <span
              className="ml-2 hidden max-w-[12rem] items-center gap-2 truncate text-fg-muted sm:inline-flex"
              title={user.display_name}
            >
              <span
                aria-hidden
                className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-accent-soft text-2xs font-semibold uppercase text-accent-text"
              >
                {user.display_name.slice(0, 1)}
              </span>
              <span className="truncate">{user.display_name}</span>
            </span>
            <Button variant="ghost" size="sm" onClick={onLogout} icon={<LogOut size={14} />}>
              Sign out
            </Button>
          </>
        )}
        <span aria-hidden className="mx-1 h-5 w-px bg-line" />
        <ThemeToggle />
      </nav>
    </header>
  );
}
