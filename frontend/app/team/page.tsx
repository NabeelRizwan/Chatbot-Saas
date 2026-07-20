import { DashboardShell } from "@/components/layout/dashboard-shell";
import { PlatformClient } from "@/components/platform/platform-client";

export default function TeamPage() {
  return (
    <DashboardShell>
      <PlatformClient view="team" />
    </DashboardShell>
  );
}
