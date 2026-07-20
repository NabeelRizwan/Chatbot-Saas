import { DashboardShell } from "@/components/layout/dashboard-shell";
import { PlatformClient } from "@/components/platform/platform-client";

export default function SettingsPage() {
  return (
    <DashboardShell>
      <PlatformClient view="settings" />
    </DashboardShell>
  );
}
