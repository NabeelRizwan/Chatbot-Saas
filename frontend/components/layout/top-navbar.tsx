"use client";

import { Bell, Building2, ChevronRight, LogOut, Menu, Moon, Search, Sun, UserRound } from "lucide-react";
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
import { logout } from "@/services/auth-service";
import { getOrganizations } from "@/services/organization-service";
import { useAuthStore } from "@/store/auth-store";
import { useUiStore } from "@/store/ui-store";
import type { Organization } from "@/types/organization";

export function TopNavbar() {
  const router = useRouter();
  const mounted = useMounted();
  const theme = useUiStore((state) => state.theme);
  const toggleTheme = useUiStore((state) => state.toggleTheme);
  const setMobileSidebarOpen = useUiStore((state) => state.setMobileSidebarOpen);
  const user = useAuthStore((state) => state.user);
  const refreshToken = useAuthStore((state) => state.refreshToken);
  const selectedOrganizationId = useAuthStore((state) => state.selectedOrganizationId);
  const setSelectedOrganizationId = useAuthStore((state) => state.setSelectedOrganizationId);
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
          setSelectedOrganizationId(items[0].id);
        }
      })
      .catch(() => setOrganizations([]));
  }, [selectedOrganizationId, setSelectedOrganizationId, user]);

  async function signOut() {
    try {
      await logout(refreshToken);
    } finally {
      clearSession();
      router.push("/login");
    }
  }

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur-xl">
      <div className="flex h-16 items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <Button className="lg:hidden" size="icon" variant="ghost" onClick={() => setMobileSidebarOpen(true)}>
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
          <div className="hidden h-10 w-72 items-center gap-2 rounded-lg border border-border bg-card px-3 text-sm text-muted-foreground md:flex">
            <Search className="h-4 w-4" />
            <span>Search bots, docs, conversations</span>
          </div>
          <Button size="icon" variant="ghost" onClick={toggleTheme}>
            {mounted && theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </Button>
          <Button size="icon" variant="ghost">
            <Bell className="h-5 w-5" />
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button className="gap-2" variant="outline">
                <Building2 className="h-4 w-4" />
                <span className="hidden max-w-36 truncate sm:inline">
                  {organizations.find((org) => org.id === selectedOrganizationId)?.name ?? "Workspace"}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {organizations.map((org) => (
                <DropdownMenuItem key={org.id} onClick={() => setSelectedOrganizationId(org.id)}>
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
              <Button className="gap-2" variant="outline">
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
