import { DashboardShell } from "@/components/layout/dashboard-shell";
import { InboxClient } from "@/components/inbox/inbox-client";

export default function ConversationsPage() {
  return (
    <DashboardShell>
      <InboxClient />
    </DashboardShell>
  );
}
