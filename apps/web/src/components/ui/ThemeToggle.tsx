"use client";

import { Moon, Sun } from "lucide-react";

import { setThemeChoice, useTheme } from "@/lib/theme";

import { IconButton } from "./IconButton";

/** Header toggle: light <-> dark. The choice is remembered; without one the OS setting applies. */
export function ThemeToggle() {
  const { theme } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <IconButton label={`Switch to ${next} theme`} onClick={() => setThemeChoice(next)}>
      {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
    </IconButton>
  );
}
