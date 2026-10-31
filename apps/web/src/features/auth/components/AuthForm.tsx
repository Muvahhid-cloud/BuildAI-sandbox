"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api/errors";

import { login, register } from "../api";

type Mode = "login" | "register";

const COPY: Record<
  Mode,
  { title: string; submit: string; switchText: string; switchHref: string }
> = {
  login: {
    title: "Sign in",
    submit: "Sign in",
    switchText: "No account? Create one",
    switchHref: "/register",
  },
  register: {
    title: "Create account",
    submit: "Create account",
    switchText: "Already registered? Sign in",
    switchHref: "/login",
  },
};

/** Only allow same-site relative redirects. */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/projects";
}

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      mode === "login"
        ? login({ email, password })
        : register({ email, password, display_name: displayName }),
    onSuccess: () => router.replace(next),
  });

  const error = mutation.error instanceof ApiError ? mutation.error : null;
  const fieldErrors = error?.fieldErrors() ?? {};
  const copy = COPY[mode];

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    mutation.mutate();
  }

  return (
    <form onSubmit={onSubmit} className="flex w-full max-w-sm flex-col gap-4" noValidate>
      <h1 className="text-2xl font-semibold">{copy.title}</h1>

      {mode === "register" && (
        <Field
          label="Name"
          name="display_name"
          value={displayName}
          onChange={setDisplayName}
          error={fieldErrors.display_name}
          autoComplete="name"
        />
      )}
      <Field
        label="Email"
        name="email"
        type="email"
        value={email}
        onChange={setEmail}
        error={fieldErrors.email}
        autoComplete="email"
      />
      <Field
        label="Password"
        name="password"
        type="password"
        value={password}
        onChange={setPassword}
        error={fieldErrors.password}
        autoComplete={mode === "login" ? "current-password" : "new-password"}
        hint={mode === "register" ? "At least 10 characters" : undefined}
      />

      {error && Object.keys(fieldErrors).length === 0 && (
        <p role="alert" className="text-sm text-red-600">
          {error.message}
        </p>
      )}

      <button
        type="submit"
        disabled={mutation.isPending}
        className="rounded-md bg-neutral-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900"
      >
        {mutation.isPending ? "Please wait…" : copy.submit}
      </button>
      <Link href={copy.switchHref} className="text-sm text-neutral-600 underline">
        {copy.switchText}
      </Link>
    </form>
  );
}

function Field(props: {
  label: string;
  name: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  error?: string;
  hint?: string;
  autoComplete?: string;
}) {
  const id = `field-${props.name}`;
  return (
    <div className="flex flex-col gap-1 text-sm">
      <label htmlFor={id} className="font-medium">
        {props.label}
      </label>
      <input
        id={id}
        name={props.name}
        type={props.type ?? "text"}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        autoComplete={props.autoComplete}
        aria-invalid={props.error ? true : undefined}
        aria-describedby={props.error ? `${id}-error` : undefined}
        className="rounded-md border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700"
      />
      {props.hint && !props.error && <span className="text-neutral-500">{props.hint}</span>}
      {props.error && (
        <span id={`${id}-error`} className="text-red-600">
          {props.error}
        </span>
      )}
    </div>
  );
}
