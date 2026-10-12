import { HostedChat } from "@/components/chat/hosted-chat";

export default async function PreviewChatPage({ params }: { params: Promise<{ botId: string }> }) {
  const { botId } = await params;
  return <HostedChat botId={botId} preview />;
}
