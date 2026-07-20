import { create } from "zustand";
import { persist } from "zustand/middleware";

export type AuthUser = {
  id: string;
  name: string;
  email: string;
  role: "owner" | "admin" | "member";
  is_admin?: boolean;
  bio?: string;
  avatar_url?: string;
  preferences?: {
    theme?: string;
    language?: string;
    notifications?: {
      email: boolean;
      in_app: boolean;
    };
  };
};

type AuthState = {
  accessToken: string | null;
  refreshToken: string | null;
  selectedOrganizationId: string | null;
  user: AuthUser | null;
  setSession: (tokens: { accessToken: string; refreshToken: string }, user: AuthUser) => void;
  setUser: (user: AuthUser) => void;
  setSelectedOrganizationId: (organizationId: string | null) => void;
  clearSession: () => void;
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      selectedOrganizationId: null,
      user: null,
      setSession: (tokens, user) => set({ accessToken: tokens.accessToken, refreshToken: tokens.refreshToken, user }),
      setUser: (user) => set({ user }),
      setSelectedOrganizationId: (organizationId) => set({ selectedOrganizationId: organizationId }),
      clearSession: () => set({ accessToken: null, refreshToken: null, selectedOrganizationId: null, user: null }),
    }),
    {
      name: "chatbot-saas-auth",
    },
  ),
);
