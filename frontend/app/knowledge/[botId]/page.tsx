import { DashboardShell } from "@/components/layout/dashboard-shell";
import { KnowledgeBotClient } from "@/components/knowledge/knowledge-bot-client";

export default async function BotKnowledgePage({ params }: { params: Promise<{ botId: string }> }) {
  const { botId } = await params;

  return (
    <DashboardShell>
      <KnowledgeBotClient botId={botId} />
    </DashboardShell>
  );
}
