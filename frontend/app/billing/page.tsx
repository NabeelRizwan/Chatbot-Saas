import { DashboardShell } from "@/components/layout/dashboard-shell";
import { PlatformClient } from "@/components/platform/platform-client";

export default function BillingPage() {
  return (
    <DashboardShell>
      <PlatformClient view="billing" />
    </DashboardShell>
  );
}
