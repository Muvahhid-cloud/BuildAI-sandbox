"use client";

import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import { useEffect } from "react";
import { create } from "zustand";

import { cn } from "@/lib/cn";

export type ToastTone = "success" | "error" | "info";

export interface ToastItem {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastState {
  items: ToastItem[];
  push: (tone: ToastTone, message: string) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useToastStore = create<ToastState>((set) => ({
  items: [],
  push: (tone, message) =>
    set((s) => ({ items: [...s.items.slice(-3), { id: nextId++, tone, message }] })),
  dismiss: (id) => set((s) => ({ items: s.items.filter((t) => t.id !== id) })),
}));

/** Fire a toast from anywhere (event handlers, mutation callbacks). */
export const toast = {
  success: (message: string) => useToastStore.getState().push("success", message),
  error: (message: string) => useToastStore.getState().push("error", message),
  info: (message: string) => useToastStore.getState().push("info", message),
};

const LIFETIME_MS = { success: 4000, info: 4000, error: 7000 } as const;

const ICON = {
  success: <CircleCheck size={16} className="text-green-500" />,
  error: <CircleAlert size={16} className="text-red-500" />,
  info: <Info size={16} className="text-accent-text" />,
} as const;

/** The toast stack (bottom right). Announced politely; errors assertively. */
export function Toaster() {
  const items = useToastStore((s) => s.items);
  return (
    <div
      aria-label="Notifications"
      className="pointer-events-none fixed bottom-12 right-4 z-50 flex w-[min(92vw,360px)] flex-col gap-2"
    >
      {items.map((item) => (
        <ToastCard key={item.id} item={item} />
      ))}
    </div>
  );
}

function ToastCard({ item }: { item: ToastItem }) {
  const dismiss = useToastStore((s) => s.dismiss);
  useEffect(() => {
    const timer = window.setTimeout(() => dismiss(item.id), LIFETIME_MS[item.tone]);
    return () => window.clearTimeout(timer);
  }, [item.id, item.tone, dismiss]);
  return (
    <div
      aria-live={item.tone === "error" ? "assertive" : "polite"}
      data-toast={item.tone}
      className={cn(
        "glass pointer-events-auto flex animate-toast-in items-start gap-2.5 rounded-xl px-3 py-2.5 text-sm text-fg shadow-lg",
      )}
    >
      <span aria-hidden className="mt-0.5">
        {ICON[item.tone]}
      </span>
      <p className="min-w-0 flex-1 break-words">{item.message}</p>
      <button
        type="button"
        onClick={() => dismiss(item.id)}
        aria-label="Dismiss notification"
        className="rounded p-0.5 text-fg-subtle hover:text-fg"
      >
        <X size={14} aria-hidden />
      </button>
    </div>
  );
}
