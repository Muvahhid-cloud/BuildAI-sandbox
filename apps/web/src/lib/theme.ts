"use client";

// Light / dark theme: the choice is kept in localStorage; without one the OS setting applies.
// lib/theme-script.ts sets it before first paint (app/layout.tsx) so the page never flashes.
import { useSyncExternalStore } from "react";

import { THEME_KEY } from "./theme-script";

export type Theme = "light" | "dark";
export type ThemeChoice = Theme | "system";

const listeners = new Set<() => void>();

function systemTheme(): Theme {
  return typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function storedChoice(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system"; // private mode / blocked storage
  }
}

export function resolveTheme(choice: ThemeChoice): Theme {
  return choice === "system" ? systemTheme() : choice;
}

function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme;
}

export function setThemeChoice(choice: ThemeChoice) {
  try {
    if (choice === "system") window.localStorage.removeItem(THEME_KEY);
    else window.localStorage.setItem(THEME_KEY, choice);
  } catch {
    // The theme still applies for this page view.
  }
  apply(resolveTheme(choice));
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const media =
    typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)")
      : null;
  const onSystem = () => {
    if (storedChoice() === "system") {
      apply(systemTheme());
      listener();
    }
  };
  media?.addEventListener?.("change", onSystem);
  return () => {
    listeners.delete(listener);
    media?.removeEventListener?.("change", onSystem);
  };
}

/** The theme in effect and the user's choice ("system" until they pick one). */
export function useTheme(): { theme: Theme; choice: ThemeChoice } {
  const choice = useSyncExternalStore<ThemeChoice>(subscribe, storedChoice, () => "system");
  const theme = useSyncExternalStore<Theme>(
    subscribe,
    () => resolveTheme(storedChoice()),
    () => "light",
  );
  return { theme, choice };
}
