import { DashboardShell } from "@/components/layout/dashboard-shell";
import { BotsPageClient } from "@/components/bots/bots-page-client";

export default function BotsPage() {
  return (
    <DashboardShell>
      <BotsPageClient />
    </DashboardShell>
  );
}
