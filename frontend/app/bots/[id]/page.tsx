"use client";

import { ArrowLeft, RefreshCcw, Settings, Database, Sliders } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AdvancedBotBuilder } from "@/components/bots/advanced-bot-builder";
import { BotAnalyticsCard } from "@/components/bots/bot-analytics-card";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useBotStore } from "@/store/bot-store";
import { useToastStore } from "@/store/toast-store";
import type { BotBuilderInput, WidgetConfig } from "@/types/bot";
import { KnowledgeBotClient } from "@/components/knowledge/knowledge-bot-client";
import { WidgetCustomizer } from "@/components/bots/widget-customizer";

export default function EditBotPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const bot = useBotStore((state) => state.selectedBot);
  const error = useBotStore((state) => state.error);
  const selectedLoading = useBotStore((state) => state.selectedLoading);
  const mutating = useBotStore((state) => state.mutating);
  const fetchBot = useBotStore((state) => state.fetchBot);
  const updateBot = useBotStore((state) => state.updateBot);
  const showToast = useToastStore((state) => state.showToast);

  const [activeTab, setActiveTab] = useState<"settings" | "knowledge" | "widget">("settings");

  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const tab = params.get("tab");
      if (tab === "knowledge" || tab === "widget" || tab === "settings") {
        setActiveTab(tab);
      }
    }
  }, []);

  useEffect(() => {
    void fetchBot(params.id);
  }, [fetchBot, params.id]);

  async function handleSubmit(values: BotBuilderInput) {
    try {
      const updated = await updateBot(params.id, values);
      showToast({
        title: "Bot updated",
        description: `${updated.name} settings were saved.`,
        variant: "success",
      });
      router.push("/bots");
    } catch (updateError) {
      showToast({
        title: "Update failed",
        description: updateError instanceof Error ? updateError.message : "The bot could not be updated.",
        variant: "error",
      });
    }
  }

  async function handleWidgetSave(values: { widgetConfig: WidgetConfig; welcomeMessage: string; allowedOrigins: string[] }) {
    await updateBot(params.id, values);
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
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-primary">Edit bot</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-normal sm:text-4xl">
                {bot?.name ?? "Bot Settings"}
              </h1>
            </div>
            
            {/* Tab controls */}
            {bot && (
              <div className="flex bg-muted p-1 rounded-lg border border-border w-fit text-xs font-semibold">
                <button
                  onClick={() => setActiveTab("settings")}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-colors ${
                    activeTab === "settings" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Settings className="h-3.5 w-3.5" />
                  General Settings
                </button>
                <button
                  onClick={() => setActiveTab("knowledge")}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-colors ${
                    activeTab === "knowledge" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Database className="h-3.5 w-3.5" />
                  Knowledge Base
                </button>
                <button
                  onClick={() => setActiveTab("widget")}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-colors ${
                    activeTab === "widget" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Sliders className="h-3.5 w-3.5" />
                  Widget Customizer
                </button>
              </div>
            )}
          </div>
        </div>

        {selectedLoading ? (
          <EditLoading />
        ) : bot ? (
          <div className="space-y-6">
            {activeTab === "settings" && (
              <>
                <BotAnalyticsCard botId={bot.id} />
                <AdvancedBotBuilder mode="edit" bot={bot} loading={mutating} onSubmit={handleSubmit} />
              </>
            )}

            {activeTab === "knowledge" && (
              <KnowledgeBotClient botId={params.id} />
            )}

            {activeTab === "widget" && (
              <WidgetCustomizer bot={bot} onSave={handleWidgetSave} saving={mutating} />
            )}
          </div>
        ) : (
          <Card>
            <CardContent className="space-y-4 p-6">
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
                {error ?? "Unable to load this bot."}
              </div>
              <Button onClick={() => fetchBot(params.id)}>
                <RefreshCcw className="h-4 w-4" />
                Retry
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </DashboardShell>
  );
}

function EditLoading() {
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
      <div className="space-y-6">
        <div className="rounded-lg border border-border bg-card p-5">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="mt-6 h-11 w-full" />
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Skeleton className="h-11 w-full" />
            <Skeleton className="h-11 w-full" />
          </div>
        </div>
        <div className="rounded-lg border border-border bg-card p-5">
          <Skeleton className="h-5 w-56" />
          <Skeleton className="mt-6 h-24 w-full" />
          <Skeleton className="mt-4 h-44 w-full" />
        </div>
      </div>
      <div className="rounded-lg border border-border bg-card p-5">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="mt-6 h-24 w-full" />
        <Skeleton className="mt-4 h-10 w-full" />
      </div>
    </div>
  );
}
