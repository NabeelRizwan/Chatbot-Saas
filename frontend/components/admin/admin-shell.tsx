"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { adminService } from "@/services/admin-service";
import { ApiServiceError } from "@/services/api";
import { useAuthStore } from "@/store/auth-store";

export function AdminShell({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((state) => state.accessToken);
  const router = useRouter();
  const pathname = usePathname();
  const [verifiedToken, setVerifiedToken] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    if (!token) return;
    adminService.session().then(() => {
      if (active) setVerifiedToken(token);
    }).catch((err: unknown) => {
      if (!active) return;
      if (err instanceof ApiServiceError && err.status === 403) {
        const state = useAuthStore.getState();
        if (state.user) state.setUser({ ...state.user, is_admin: false });
        router.replace("/");
      }
      else if (err instanceof ApiServiceError && err.status === 401) router.replace("/login");
      else setError("Unable to verify admin access. Reload to retry.");
    });
    return () => { active = false; };
  }, [token, router]);

  if (!token || verifiedToken !== token) return <p role="status">{error || "Checking admin access…"}</p>;
  return <div className="space-y-6">
    <header><h1 className="text-2xl font-semibold">Platform admin</h1><p className="mt-1 text-sm text-muted-foreground">Customer operations and platform-owned generation credentials.</p></header>
    <nav aria-label="Admin navigation" className="flex flex-wrap gap-2 border-b border-border pb-4">
      {[["Overview", "/admin"], ["Organizations", "/admin/organizations"], ["Bots", "/admin/bots"], ["API Credentials", "/admin/api-credentials"]].map(([label, href]) =>
        <Link key={href} href={href} aria-current={pathname === href ? "page" : undefined} className={`rounded-lg px-4 py-2 text-sm ${pathname === href ? "bg-primary text-primary-foreground" : "bg-muted"}`}>{label}</Link>)}
    </nav>
    {children}
  </div>;
}
