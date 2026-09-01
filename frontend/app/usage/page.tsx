import { DashboardShell } from "@/components/layout/dashboard-shell";
import { PlatformClient } from "@/components/platform/platform-client";

export default function UsagePage() {
  return (
    <DashboardShell>
      <PlatformClient view="usage" />
    </DashboardShell>
  );
}
