import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores/auth-store";
import { jsonResponse, mockFetch, tokens } from "@/test/fetch";

import { AuthForm } from "./AuthForm";

const replace = vi.fn();
let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => searchParams,
}));

function renderForm(mode: "login" | "register") {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthForm mode={mode} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  replace.mockReset();
  searchParams = new URLSearchParams();
  useAuthStore.setState({ status: "anonymous", accessToken: null, user: null });
});
afterEach(() => vi.unstubAllGlobals());

describe("AuthForm", () => {
  it("logs in, stores the session and redirects to ?next", async () => {
    searchParams = new URLSearchParams({ next: "/projects/abc" });
    const fetch = mockFetch(jsonResponse(tokens()));
    renderForm("login");

    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/projects/abc"));
    expect(JSON.parse(fetch.mock.calls[0]![1]!.body as string)).toEqual({
      email: "ada@example.com",
      password: "correct-horse-battery",
    });
    expect(useAuthStore.getState().status).toBe("authenticated");
  });

  it("ignores off-site redirect targets", async () => {
    searchParams = new URLSearchParams({ next: "//evil.example" });
    mockFetch(jsonResponse(tokens()));
    renderForm("login");
    await userEvent.type(screen.getByLabelText("Email"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/projects"));
  });

  it("shows the server error on failed login", async () => {
    mockFetch(
      jsonResponse(
        { error: { code: "UNAUTHORIZED", message: "Invalid email or password", details: [] } },
        401,
      ),
    );
    renderForm("login");
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows field-level validation errors on register", async () => {
    mockFetch(
      jsonResponse(
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "Request validation failed",
            details: [{ path: "/password", message: "String should have at least 10 characters" }],
          },
        },
        422,
      ),
    );
    renderForm("register");
    await userEvent.type(screen.getByLabelText("Name"), "Ada");
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("String should have at least 10 characters")).toBeVisible();
    expect(screen.getByLabelText("Password")).toHaveAttribute("aria-invalid", "true");
  });
});
