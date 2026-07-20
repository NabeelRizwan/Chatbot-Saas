import { DashboardShell } from "@/components/layout/dashboard-shell";
import { PlatformClient } from "@/components/platform/platform-client";

export default function AnalyticsPage() {
  return (
    <DashboardShell>
      <PlatformClient view="analytics" />
    </DashboardShell>
  );
}
