"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Logo } from "@/components/Logo";
import { Button, Callout, Card, Input } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";

import { login, register } from "../api";

type Mode = "login" | "register";

const COPY: Record<
  Mode,
  { title: string; tagline: string; submit: string; switchText: string; switchHref: string }
> = {
  login: {
    title: "Sign in",
    tagline: "Welcome back. Your projects are waiting.",
    submit: "Sign in",
    switchText: "No account? Create one",
    switchHref: "/register",
  },
  register: {
    title: "Create account",
    tagline: "Describe a house, get a 3D model you can explore.",
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
    <div className="w-full max-w-sm animate-rise-in">
      <div className="mb-6 flex flex-col items-center gap-3 text-center">
        <Logo size={36} />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{copy.title}</h1>
          <p className="mt-1 text-sm text-fg-subtle">{copy.tagline}</p>
        </div>
      </div>
      <Card className="p-5 shadow-md sm:p-6">
        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
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
            <Callout tone="danger" role="alert" className="py-2">
              {error.message}
            </Callout>
          )}

          <Button type="submit" variant="primary" size="lg" disabled={mutation.isPending}>
            {mutation.isPending ? "Please wait…" : copy.submit}
          </Button>
        </form>
      </Card>
      <p className="mt-4 text-center text-sm">
        <Link
          href={copy.switchHref}
          className="text-fg-muted underline decoration-line-strong underline-offset-4 transition-colors hover:text-fg"
        >
          {copy.switchText}
        </Link>
      </p>
    </div>
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
    <div className="flex flex-col gap-1.5 text-sm">
      <label htmlFor={id} className="font-medium">
        {props.label}
      </label>
      <Input
        id={id}
        name={props.name}
        type={props.type ?? "text"}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        autoComplete={props.autoComplete}
        aria-invalid={props.error ? true : undefined}
        aria-describedby={props.error ? `${id}-error` : undefined}
        className="h-10 px-3"
      />
      {props.hint && !props.error && <span className="text-xs text-fg-subtle">{props.hint}</span>}
      {props.error && (
        <span id={`${id}-error`} className="text-xs text-red-600 dark:text-red-400">
          {props.error}
        </span>
      )}
    </div>
  );
}
