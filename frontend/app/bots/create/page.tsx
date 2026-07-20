"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { AdvancedBotBuilder } from "@/components/bots/advanced-bot-builder";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Button } from "@/components/ui/button";
import { useBotStore } from "@/store/bot-store";
import { useAuthStore } from "@/store/auth-store";
import { useToastStore } from "@/store/toast-store";
import { useKnowledgeStore } from "@/store/knowledge-store";
import type { BotCreateInput, BotUpdateInput } from "@/types/bot";

export default function CreateBotPage() {
  const router = useRouter();
  const createBot = useBotStore((state) => state.createBot);
  const mutating = useBotStore((state) => state.mutating);
  const selectedOrganizationId = useAuthStore((state) => state.selectedOrganizationId);
  const showToast = useToastStore((state) => state.showToast);

  async function handleSubmit(values: BotCreateInput | BotUpdateInput, files?: File[]) {
    try {
      const bot = await createBot({ ...(values as BotCreateInput), organizationId: selectedOrganizationId });
      
      if (files && files.length > 0) {
        showToast({
          title: "Bot created",
          description: `${bot.name} created. Uploading ${files.length} files...`,
          variant: "success",
        });
        const uploadFile = useKnowledgeStore.getState().uploadFile;
        // Upload concurrently or sequentially
        await Promise.allSettled(files.map(f => uploadFile(bot.id, f)));
      }

      showToast({
        title: "Setup Complete",
        description: `${bot.name} is ready.`,
        variant: "success",
      });
      router.push(`/bots/${bot.id}?tab=knowledge`);
    } catch (error) {
      showToast({
        title: "Create failed",
        description: error instanceof Error ? error.message : "The bot could not be created.",
        variant: "error",
      });
    }
  }

  return (
    <DashboardShell>
      <div className="space-y-6">
        <div className="flex flex-col gap-4">
          <Button asChild variant="ghost" className="w-fit px-0">
            <Link href="/bots">
              <ArrowLeft className="h-4 w-4" />
              Back to bots
            </Link>
          </Button>
          <div>
            <p className="text-sm font-medium text-primary">Create bot</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-normal sm:text-4xl">New Assistant</h1>
            <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
              Configure the provider, model, API key, welcome message, and system behavior.
            </p>
          </div>
        </div>
        <AdvancedBotBuilder mode="create" loading={mutating} onSubmit={handleSubmit} />
      </div>
    </DashboardShell>
  );
}
