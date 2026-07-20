import { DashboardShell } from "@/components/layout/dashboard-shell";
import { KnowledgeIndexClient } from "@/components/knowledge/knowledge-index-client";

export default function KnowledgePage() {
  return (
    <DashboardShell>
      <KnowledgeIndexClient />
    </DashboardShell>
  );
}
