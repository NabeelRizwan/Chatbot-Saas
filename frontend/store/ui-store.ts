import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeMode = "light" | "dark" | "system";

type UiState = {
  sidebarCollapsed: boolean;
  mobileSidebarOpen: boolean;
  theme: ThemeMode;
  toggleSidebar: () => void;
  setMobileSidebarOpen: (open: boolean) => void;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
};

export const useUiStore = create<UiState>()(
  persist(
    (set, get) => ({
      sidebarCollapsed: false,
      mobileSidebarOpen: false,
      theme: "light",
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setMobileSidebarOpen: (open) => set({ mobileSidebarOpen: open }),
      setTheme: (theme) => set({ theme }),
      toggleTheme: () => {
        const current = get().theme;
        const isDark = current === "dark" || (current === "system" && typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches);
        set({ theme: isDark ? "light" : "dark" });
      },
    }),
    {
      name: "chatbot-saas-ui",
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        theme: state.theme,
      }),
    },
  ),
);
