"use client";

import { Building2, ChevronRight, LogOut, Menu, Moon, Search, Sun, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useMounted } from "@/hooks/use-mounted";
import { useResolvedTheme } from "@/components/layout/theme-provider";
import { hasOrganizationRole } from "@/lib/organization-roles";
import { logout } from "@/services/auth-service";
import { getOrganizations } from "@/services/organization-service";
import { useAuthStore } from "@/store/auth-store";
import { useUiStore } from "@/store/ui-store";
import type { Organization } from "@/types/organization";

export function TopNavbar() {
  const router = useRouter();
  const mounted = useMounted();
  const theme = useResolvedTheme();
  const toggleTheme = useUiStore((state) => state.toggleTheme);
  const setMobileSidebarOpen = useUiStore((state) => state.setMobileSidebarOpen);
  const user = useAuthStore((state) => state.user);
  const selectedOrganizationId = useAuthStore((state) => state.selectedOrganizationId);
  const activeOrganizationRole = useAuthStore((state) => state.activeOrganizationRole);
  const setSelectedOrganization = useAuthStore((state) => state.setSelectedOrganization);
  const clearSession = useAuthStore((state) => state.clearSession);
  const [organizations, setOrganizations] = useState<Organization[]>([]);

  useEffect(() => {
    if (!user) {
      setOrganizations([]);
      return;
    }
    getOrganizations()
      .then((items) => {
        setOrganizations(items);
        if (!selectedOrganizationId && items[0]) {
          setSelectedOrganization(items[0].id, items[0].role);
        } else if (selectedOrganizationId) {
          const selected = items.find((item) => item.id === selectedOrganizationId);
          if (selected) setSelectedOrganization(selected.id, selected.role);
        }
      })
      .catch(() => setOrganizations([]));
  }, [selectedOrganizationId, setSelectedOrganization, user]);

  async function signOut() {
    try {
      await logout();
    } finally {
      clearSession();
      router.push("/login");
    }
  }

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur-xl">
      <div className="flex h-16 items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <Button className="lg:hidden" size="icon" variant="ghost" aria-label="Open navigation" onClick={() => setMobileSidebarOpen(true)}>
            <Menu className="h-5 w-5" />
          </Button>
          <div className="hidden items-center gap-2 text-sm text-muted-foreground sm:flex">
            <span>Workspace</span>
            <ChevronRight className="h-4 w-4" />
            <span className="font-medium text-foreground">
              {organizations.find((org) => org.id === selectedOrganizationId)?.name ?? "Dashboard"}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" aria-label="Find in dashboard">
                <Search className="h-4 w-4" />
                <span className="hidden sm:inline">Find in…</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem asChild><Link href="/bots">Bots</Link></DropdownMenuItem>
              {hasOrganizationRole(activeOrganizationRole, "member") && <>
                <DropdownMenuItem asChild><Link href="/knowledge">Knowledge Base</Link></DropdownMenuItem>
                <DropdownMenuItem asChild><Link href="/conversations">Conversations</Link></DropdownMenuItem>
              </>}
            </DropdownMenuContent>
          </DropdownMenu>
          <Button size="icon" variant="ghost" aria-label={mounted && theme === "dark" ? "Switch to light theme" : "Switch to dark theme"} onClick={toggleTheme}>
            {mounted && theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button className="gap-2" variant="outline" aria-label="Switch workspace">
                <Building2 className="h-4 w-4" />
                <span className="hidden max-w-36 truncate sm:inline">
                  {organizations.find((org) => org.id === selectedOrganizationId)?.name ?? "Workspace"}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {organizations.map((org) => (
                <DropdownMenuItem key={org.id} onClick={() => setSelectedOrganization(org.id, org.role)}>
                  {org.name}
                </DropdownMenuItem>
              ))}
              <DropdownMenuItem asChild>
                <Link href="/organization">Manage workspace</Link>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button className="gap-2" variant="outline" aria-label="Account menu">
                <UserRound className="h-4 w-4" />
                <span className="hidden sm:inline">{user?.name ?? "Account"}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem asChild>
                <Link href="/profile">Profile</Link>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link href="/billing">Billing</Link>
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => void signOut()}>
                <LogOut className="h-4 w-4" />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
}
