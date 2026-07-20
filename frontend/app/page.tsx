import { DashboardShell } from "@/components/layout/dashboard-shell";
import { DashboardHome } from "@/components/dashboard/dashboard-home";

export default function HomePage() {
  return (
    <DashboardShell>
      <DashboardHome />
    </DashboardShell>
  );
}
