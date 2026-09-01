import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { OrganizationRole } from "@/types/organization";

export type AuthUser = {
  id: string;
  name: string;
  email: string;
  is_admin?: boolean;
  bio?: string;
  avatar_url?: string;
  preferences?: {
    theme?: string;
    language?: string;
    notifications?: { email: boolean; in_app: boolean };
  };
};

type AuthState = {
  accessToken: string | null;
  selectedOrganizationId: string | null;
  activeOrganizationRole: OrganizationRole | null;
  user: AuthUser | null;
  setSession: (accessToken: string, user: AuthUser) => void;
  setUser: (user: AuthUser) => void;
  setSelectedOrganization: (organizationId: string | null, role: OrganizationRole | null) => void;
  consumeLegacyRefreshToken: () => string | null;
  clearSession: () => void;
};

const STORAGE_KEY = "chatbot-saas-auth";

function consumeLegacyRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { state?: Record<string, unknown>; version?: number };
    const legacy = typeof parsed.state?.refreshToken === "string" ? parsed.state.refreshToken : null;
    if (parsed.state) {
      delete parsed.state.accessToken;
      delete parsed.state.refreshToken;
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
    }
    return legacy;
  } catch {
    window.localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      selectedOrganizationId: null,
      activeOrganizationRole: null,
      user: null,
      setSession: (accessToken, user) => set({ accessToken, user }),
      setUser: (user) => set({ user }),
      setSelectedOrganization: (organizationId, role) =>
        set({ selectedOrganizationId: organizationId, activeOrganizationRole: role }),
      consumeLegacyRefreshToken,
      clearSession: () =>
        set({ accessToken: null, selectedOrganizationId: null, activeOrganizationRole: null, user: null }),
    }),
    {
      name: STORAGE_KEY,
      partialize: (state) => ({
        selectedOrganizationId: state.selectedOrganizationId,
        activeOrganizationRole: state.activeOrganizationRole,
        user: state.user,
      }),
      merge: (persisted, current) => {
        const state = persisted as Partial<AuthState>;
        return {
          ...current,
          accessToken: null,
          selectedOrganizationId: state.selectedOrganizationId ?? null,
          activeOrganizationRole: state.activeOrganizationRole ?? null,
          user: state.user ?? null,
        };
      },
    },
  ),
);
