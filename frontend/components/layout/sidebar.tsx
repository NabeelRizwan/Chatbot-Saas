"use client";

import {
  BarChart3,
  Bot,
  CreditCard,
  ChevronLeft,
  Home,
  MessagesSquare,
  PanelLeft,
  Settings,
  Database,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { hasOrganizationRole } from "@/lib/organization-roles";
import { useAuthStore } from "@/store/auth-store";
import type { OrganizationRole } from "@/types/organization";
import { useUiStore } from "@/store/ui-store";

const navItems: Array<{ label: string; href: string; icon: typeof Home; minimumRole?: OrganizationRole }> = [
  { label: "Dashboard", href: "/", icon: Home },
  { label: "Bots", href: "/bots", icon: Bot },
  { label: "Knowledge Base", href: "/knowledge", icon: Database, minimumRole: "member" },
  { label: "Conversations", href: "/conversations", icon: MessagesSquare, minimumRole: "member" },
  { label: "Analytics", href: "/analytics", icon: BarChart3, minimumRole: "member" },
  { label: "Team", href: "/team", icon: Users, minimumRole: "member" },
  { label: "Billing", href: "/billing", icon: CreditCard, minimumRole: "member" },
  { label: "Settings", href: "/settings", icon: Settings, minimumRole: "member" },
];

export function Sidebar() {
  const collapsed = useUiStore((state) => state.sidebarCollapsed);
  const mobileOpen = useUiStore((state) => state.mobileSidebarOpen);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);
  const setMobileSidebarOpen = useUiStore((state) => state.setMobileSidebarOpen);
  const pathname = usePathname();
  const activeOrganizationRole = useAuthStore((state) => state.activeOrganizationRole);

  return (
    <>
      <div
        className={cn(
          "fixed inset-0 z-40 bg-background/70 backdrop-blur-sm lg:hidden",
          mobileOpen ? "block" : "hidden",
        )}
        onClick={() => setMobileSidebarOpen(false)}
      />
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex flex-col border-r border-border bg-card/95 backdrop-blur-xl transition-all duration-300",
          collapsed ? "lg:w-20" : "lg:w-72",
          mobileOpen ? "w-72 translate-x-0" : "w-72 -translate-x-full lg:translate-x-0",
        )}
      >
        <div className="flex h-16 items-center justify-between px-4">
          <Link href="/" className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Bot className="h-5 w-5" />
            </div>
            {!collapsed && <span className="truncate text-sm font-semibold">Chatbot SaaS</span>}
          </Link>
          <Button className="lg:hidden" size="icon" variant="ghost" onClick={() => setMobileSidebarOpen(false)}>
            <X className="h-5 w-5" />
          </Button>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-4">
          {navItems.filter((item) => !item.minimumRole || hasOrganizationRole(activeOrganizationRole, item.minimumRole)).map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.label}
                href={item.href}
                className={cn(
                  "flex h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                  active && "bg-primary/10 text-primary",
                  collapsed && "justify-center px-0",
                )}
              >
                <item.icon className="h-5 w-5 shrink-0" />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-border p-3">
          <Button className="hidden w-full lg:flex" variant="ghost" onClick={toggleSidebar}>
            {collapsed ? <PanelLeft className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            {!collapsed && "Collapse"}
          </Button>
        </div>
      </aside>
    </>
  );
}
