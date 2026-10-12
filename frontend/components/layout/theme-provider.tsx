"use client";

import { useEffect, useState } from "react";

import { useUiStore } from "@/store/ui-store";

export function useResolvedTheme() {
  const theme = useUiStore((state) => state.theme);
  const [systemDark, setSystemDark] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setSystemDark(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return theme === "system" ? (systemDark ? "dark" : "light") : theme;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useResolvedTheme();

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    root.style.colorScheme = theme;
  }, [theme]);

  return <>{children}</>;
}
