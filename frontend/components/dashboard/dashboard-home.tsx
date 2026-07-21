"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Activity, Bot, MessageSquare, Sparkles, Clock, AlertTriangle, Loader2 } from "lucide-react";

import { StatCard } from "@/components/dashboard/stat-card";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuthStore } from "@/store/auth-store";
import { getOrganizationAnalyticsDetails } from "@/services/analytics-service";

interface AnalyticsData {
  summary: {
    total_conversations: number;
    unique_visitors: number;
    total_messages: number;
    avg_response_time_ms: number | null;
    resolution_rate: number;
    fallback_rate: number;
    hit_rate: number;
    active_bots: number;
    total_users: number;
    conversations_today: number;
    messages_today: number;
    user_activity_score: number;
  };
  trends: { date: string; conversations: number; messages: number }[];
  top_bots: { id: number; name: string; conversations: number }[];
  top_documents: { id: number; filename: string; chunk_count: number; token_count: number; source_type: string }[];
  insights: {
    top_questions: string[];
    unanswered_questions: string[];
    knowledge_gaps: string[];
    suggested_improvements: string[];
  };
}

export function DashboardHome() {
  const selectedOrganizationId = useAuthStore((state) => state.selectedOrganizationId);
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedOrganizationId) {
      setLoading(false);
      return;
    }

    let active = true;
    setLoading(true);
    setError(null);

    getOrganizationAnalyticsDetails(selectedOrganizationId)
      .then((res) => {
        if (active) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (active) {
          console.error("Dashboard analytics error:", err);
          setError("Failed to load analytics details.");
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [selectedOrganizationId]);

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-6 text-center">
        <AlertTriangle className="mx-auto h-8 w-8 text-destructive opacity-80" />
        <h3 className="mt-2 text-sm font-semibold text-destructive">Analytics Load Failed</h3>
        <p className="mt-1 text-xs text-muted-foreground">{error || "No organization workspace selected."}</p>
      </div>
    );
  }

  const s = data.summary;
  const metrics = [
    { label: "Active bots", value: String(s.active_bots), change: `${s.total_users} team members`, icon: Bot, tone: "blue" as const },
    { label: "Conversations", value: s.total_conversations >= 1000 ? `${(s.total_conversations / 1000).toFixed(1)}k` : String(s.total_conversations), change: `+${s.conversations_today} today`, icon: MessageSquare, tone: "green" as const },
    { label: "Total messages", value: s.total_messages >= 1000 ? `${(s.total_messages / 1000).toFixed(1)}k` : String(s.total_messages), change: `+${s.messages_today} today`, icon: Sparkles, tone: "amber" as const },
    { label: "Avg response time", value: s.avg_response_time_ms ? `${(s.avg_response_time_ms / 1000).toFixed(2)}s` : "N/A", change: "Gemini / OpenAI speed", icon: Clock, tone: "neutral" as const },
  ];

  const insights = data.insights ?? {};
  const activities = [
    ...(s.conversations_today > 0 ? [`${s.conversations_today} new conversation sessions initiated today`] : []),
    ...(insights.unanswered_questions ?? []).map((q) => `Fallback triggered for query: "${q}"`),
    ...(insights.top_questions ?? []).map((q) => `Popular query processed: "${q}"`),
    ...(insights.knowledge_gaps ?? []).map((gap) => `Knowledge gap: ${gap}`),
  ];

  if (activities.length === 0) {
    activities.push(
      "No recent playground or widget chat events recorded yet.",
      "Integrate your HTML snippet on customer sites to collect live metrics."
    );
  }

  const trends = data.trends ?? [];
  const maxMessages = Math.max(...trends.map((t) => t.messages), 5);

  const rates = [
    { name: "RAG Resolution", value: `${Math.round(s.hit_rate)}%`, detail: "Queries grounded in knowledge base" },
    { name: "Fallback Rate", value: `${Math.round(s.fallback_rate)}%`, detail: "Queries routed to fallback/search" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="flex items-center gap-2 text-sm font-medium text-primary">
            <Sparkles className="h-4 w-4" />
            AI chatbot platform
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-normal sm:text-4xl">Dashboard</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Monitor bot readiness, ingestion health, provider usage, and customer support activity from one place.
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground shadow-soft">
          Backend target: <span className="font-medium text-foreground">{process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"}</span>
        </div>
      </div>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric, index) => (
          <StatCard key={metric.label} {...metric} index={index} />
        ))}
      </section>

      <section className="grid gap-4 lg:grid-cols-7">
        <motion.div className="lg:col-span-4" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
          <Card className="h-full">
            <CardHeader>
              <CardTitle>Messages Overview</CardTitle>
              <CardDescription>Visualizing query volume over the past 7 days.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex h-72 items-end gap-3 rounded-lg border border-border bg-muted/30 p-4">
                {trends.map((t, index) => {
                  const pct = Math.round((t.messages / maxMessages) * 100);
                  const weekday = new Date(t.date).toLocaleDateString(undefined, { weekday: "short" });
                  return (
                    <div key={index} className="flex flex-1 flex-col items-center h-full justify-end">
                      <div className="w-full flex-1 flex items-end">
                        <div
                          className="w-full rounded-t-md bg-gradient-to-t from-primary to-accent transition-all duration-500"
                          style={{ height: `${Math.max(4, pct)}%` }}
                          title={`${t.messages} messages, ${t.conversations} chats`}
                        />
                      </div>
                      <span className="text-[10px] font-bold text-muted-foreground mt-2 truncate w-full text-center">
                        {weekday}
                      </span>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </motion.div>

        <motion.div className="lg:col-span-3" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
          <Card className="h-full">
            <CardHeader>
              <CardTitle>Recent Activity</CardTitle>
              <CardDescription>Operational events from bots, ingestion, and preview usage.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {activities.slice(0, 4).map((activity, idx) => (
                <div key={idx} className="flex gap-3 rounded-lg border border-border bg-background p-3">
                  <div className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Activity className="h-4 w-4" />
                  </div>
                  <p className="text-sm text-muted-foreground leading-relaxed">{activity}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        </motion.div>
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        <Card className="flex flex-col justify-between">
          <CardHeader>
            <CardTitle>Suggested Improvements</CardTitle>
            <CardDescription>Actions to improve bot grounding resolution.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 pb-6">
            {(s.fallback_rate > 30 || s.total_conversations === 0) ? (
              <p className="text-xs text-muted-foreground">High fallbacks detected. Upload additional documentation to close gaps.</p>
            ) : (
              <p className="text-xs text-muted-foreground">Grounding is healthy. Keep monitoring fallback transcripts regularly.</p>
            )}
            <div className="space-y-2 mt-3">
              {s.fallback_rate > 0 && (
                <div className="text-2xs font-bold bg-amber-50 text-amber-800 border border-amber-200 rounded px-2.5 py-1">
                  Upload PDF/CSV FAQ document answering fallback logs
                </div>
              )}
              <div className="text-2xs font-bold bg-primary/5 text-primary border border-primary/10 rounded px-2.5 py-1">
                Refine welcome messages for friendly small talk greeting
              </div>
            </div>
          </CardContent>
        </Card>

        {rates.map((rate) => (
          <Card key={rate.name}>
            <CardHeader>
              <CardTitle>{rate.name}</CardTitle>
              <CardDescription>{rate.detail}</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex items-end justify-between">
                <span className="text-3xl font-semibold tracking-normal">{rate.value}</span>
                <span className="text-sm text-muted-foreground">resolved rate</span>
              </div>
              <div className="mt-4 h-2 rounded-full bg-muted">
                <div className="h-2 rounded-full bg-primary" style={{ width: rate.value }} />
              </div>
            </CardContent>
          </Card>
        ))}
      </section>
    </div>
  );
}
