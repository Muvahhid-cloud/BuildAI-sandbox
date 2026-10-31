import { apiRequest } from "@/lib/api/client";
import { tokenResponseSchema } from "@/lib/api/schemas";
import { useAuthStore } from "@/stores/auth-store";

export interface Credentials {
  email: string;
  password: string;
}

export async function login(creds: Credentials) {
  const tokens = await apiRequest("/auth/login", tokenResponseSchema, {
    method: "POST",
    body: creds,
    auth: false,
  });
  useAuthStore.getState().setSession(tokens);
  return tokens;
}

export async function register(input: Credentials & { display_name: string }) {
  const tokens = await apiRequest("/auth/register", tokenResponseSchema, {
    method: "POST",
    body: input,
    auth: false,
  });
  useAuthStore.getState().setSession(tokens);
  return tokens;
}

export async function logout() {
  try {
    await apiRequest("/auth/logout", null, { method: "POST", auth: false });
  } finally {
    useAuthStore.getState().clear();
  }
}
