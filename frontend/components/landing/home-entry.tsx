"use client";

import { useEffect } from "react";
import { DashboardHome } from "@/components/dashboard/dashboard-home";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { refreshAccessToken } from "@/services/api";
import { useAuthStore } from "@/store/auth-store";
import { LandingPage } from "./landing-page";

export function HomeEntry() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const clearSession = useAuthStore((state) => state.clearSession);

  useEffect(() => {
    if (accessToken) return;
    let active = true;
    void refreshAccessToken().catch(() => { if (active) clearSession(); });
    return () => { active = false; };
  }, [accessToken, clearSession]);

  return accessToken ? <DashboardShell><DashboardHome /></DashboardShell> : <LandingPage />;
}
