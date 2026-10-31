import { create } from "zustand";

import type { TokenResponse, User } from "@/lib/api/schemas";

export type AuthStatus = "unknown" | "authenticated" | "anonymous";

interface AuthState {
  status: AuthStatus;
  /** Short-lived JWT, kept in memory only. The refresh token is an httpOnly cookie. */
  accessToken: string | null;
  user: User | null;
  setSession: (tokens: TokenResponse) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>()((set) => ({
  status: "unknown",
  accessToken: null,
  user: null,
  setSession: (tokens) =>
    set({ status: "authenticated", accessToken: tokens.access_token, user: tokens.user }),
  clear: () => set({ status: "anonymous", accessToken: null, user: null }),
}));
