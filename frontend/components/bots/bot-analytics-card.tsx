"use client";

import { Activity, Clock3, MessageCircle, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { getBotAnalyticsSummary } from "@/services/analytics-service";
import type { AnalyticsSummary } from "@/types/analytics";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function BotAnalyticsCard({ botId }: { botId: string }) {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadSummary() {
    setLoading(true);
    setError(null);
    try {
      setSummary(await getBotAnalyticsSummary(botId));
    } catch (summaryError) {
      setError(summaryError instanceof Error ? summaryError.message : "Unable to load analytics.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadSummary();
  }, [botId]);

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-primary" />
            Widget Analytics
          </CardTitle>
          <CardDescription>Early conversation metrics for this bot.</CardDescription>
        </div>
        <Button type="button" size="icon" variant="ghost" onClick={() => void loadSummary()} disabled={loading}>
          <RefreshCw className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
        </Button>
      </CardHeader>
      <CardContent>
        {loading && !summary ? (
          <div className="grid gap-3 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-24 rounded-lg" />
            ))}
          </div>
        ) : error ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
            {error}
          </div>
        ) : summary ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-4">
              <Metric label="Chats" value={summary.totalConversations.toLocaleString()} />
              <Metric label="Messages" value={summary.totalMessages.toLocaleString()} />
              <Metric
                label="Avg response"
                value={
                  typeof summary.averageResponseTimeMs === "number"
                    ? `${Math.round(summary.averageResponseTimeMs).toLocaleString()} ms`
                    : "-"
                }
              />
              <Metric label="24h chats" value={summary.recentConversations24h.toLocaleString()} />
            </div>
            <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
              <span className="inline-flex items-center gap-2">
                <MessageCircle className="h-4 w-4" />
                {summary.recentMessages24h.toLocaleString()} messages in the last 24h
              </span>
              <span className="inline-flex items-center gap-2">
                <Clock3 className="h-4 w-4" />
                Last message {formatDate(summary.lastMessageAt)}
              </span>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 p-4">
      <p className="text-xs font-medium uppercase tracking-normal text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </div>
  );
}

function formatDate(value?: string | null) {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }

  return date.toLocaleString();
}
