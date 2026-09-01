"use client";

import { Sidebar } from "@/components/layout/sidebar";
import { TopNavbar } from "@/components/layout/top-navbar";
import { useMounted } from "@/hooks/use-mounted";
import { refreshAccessToken } from "@/services/api";
import { useAuthStore } from "@/store/auth-store";
import { useUiStore } from "@/store/ui-store";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export function DashboardShell({ children }: { children: React.ReactNode }) {
  const sidebarCollapsed = useUiStore((state) => state.sidebarCollapsed);
  const mounted = useMounted();
  const router = useRouter();
  const accessToken = useAuthStore((state) => state.accessToken);
  const clearSession = useAuthStore((state) => state.clearSession);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    if (!mounted) {
      return;
    }

    async function verifySession() {
      if (accessToken) {
        setCheckingSession(false);
        return;
      }

      try {
        // The API layer owns one browser-global refresh promise. This keeps
        // React Strict Mode and concurrent route requests from racing the
        // rotating HttpOnly refresh cookie.
        await refreshAccessToken();
        setCheckingSession(false);
        return;
      } catch {
        clearSession();
      }

      router.replace("/login");
      setCheckingSession(false);
    }

    void verifySession();
  }, [accessToken, clearSession, mounted, router]);

  if (!mounted || checkingSession || !accessToken) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <Sidebar />
      <div className={sidebarCollapsed ? "lg:pl-20" : "lg:pl-72"}>
        <TopNavbar />
        <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
