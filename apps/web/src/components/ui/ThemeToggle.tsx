"use client";

import { Moon, Sun } from "lucide-react";

import { setThemeChoice, useTheme } from "@/lib/theme";

import { IconButton } from "./IconButton";
import { Tooltip } from "./Tooltip";

/** Header toggle: light <-> dark. The choice is remembered; without one the OS setting applies. */
export function ThemeToggle() {
  const { theme } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <Tooltip content={`Switch to ${next} theme`} side="bottom" align="end">
      <IconButton label={`Switch to ${next} theme`} title="" onClick={() => setThemeChoice(next)}>
        {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
      </IconButton>
    </Tooltip>
  );
}
