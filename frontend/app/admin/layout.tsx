import { DashboardShell } from "@/components/layout/dashboard-shell";
import { AdminShell } from "@/components/admin/admin-shell";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <DashboardShell><AdminShell>{children}</AdminShell></DashboardShell>;
}
