import { DashboardShell } from "@/components/layout/dashboard-shell";
import { PlatformClient } from "@/components/platform/platform-client";

export default function SubscriptionPage() {
  return (
    <DashboardShell>
      <PlatformClient view="billing" />
    </DashboardShell>
  );
}
