import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/** Shared look of text fields (also used by forms that keep their own <input>). */
export const fieldClass =
  "w-full rounded-md border border-line-strong bg-surface px-2.5 text-sm text-fg shadow-xs " +
  "outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-subtle " +
  "hover:border-neutral-400 focus:border-accent focus:ring-3 focus:ring-ring/30 " +
  "disabled:cursor-not-allowed disabled:opacity-60 dark:hover:border-neutral-600 " +
  "aria-[invalid=true]:border-red-500";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(fieldClass, "h-8", className)} {...rest} />;
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(fieldClass, "py-2 leading-relaxed", className)} {...rest} />;
}

export function Select({ className, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(fieldClass, "h-8 pr-7", className)} {...rest} />;
}
