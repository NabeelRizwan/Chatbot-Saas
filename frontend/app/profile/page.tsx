import { DashboardShell } from "@/components/layout/dashboard-shell";
import { PlatformClient } from "@/components/platform/platform-client";

export default function ProfilePage() {
  return (
    <DashboardShell>
      <PlatformClient view="profile" />
    </DashboardShell>
  );
}
