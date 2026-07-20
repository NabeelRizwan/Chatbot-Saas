import { DashboardShell } from "@/components/layout/dashboard-shell";
import { PlatformClient } from "@/components/platform/platform-client";

export default function OrganizationPage() {
  return (
    <DashboardShell>
      <PlatformClient view="organization" />
    </DashboardShell>
  );
}
