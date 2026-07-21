"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { MessageSquare, ShieldCheck, Bot } from "lucide-react";
import { API_BASE_URL } from "@/services/api";

interface Message {
  id: number;
  user_message: string;
  assistant_response: string;
  created_at: string;
}

interface SharedData {
  session: {
    title: string;
    bot_name: string;
    created_at: string;
  };
  messages: Message[];
}

export default function PublicSharePage() {
  const params = useParams<{ token: string }>();
  const [data, setData] = useState<SharedData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadTranscript() {
      try {
        const res = await fetch(`${API_BASE_URL}/public/share/${params.token}`);
        if (!res.ok) {
          throw new Error("Transcript not found or sharing has been disabled by the owner.");
        }
        const json = await res.ok ? await res.json() : null;
        setData(json);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load the transcript.");
      } finally {
        setLoading(false);
      }
    }
    if (params.token) {
      void loadTranscript();
    }
  }, [params.token]);

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 p-4">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
          <p className="text-sm font-medium text-slate-500">Loading secure transcript...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 p-4">
        <div className="max-w-md text-center bg-card rounded-2xl border border-border p-8 shadow-md">
          <MessageSquare className="mx-auto h-12 w-12 text-slate-300 mb-4" />
          <h1 className="text-lg font-bold text-slate-900">Unavailable Transcript</h1>
          <p className="mt-2 text-xs text-muted-foreground leading-relaxed">
            {error || "This shared conversation link is invalid or has expired."}
          </p>
          <div className="mt-6 flex justify-center gap-2 text-[10px] text-muted-foreground">
            <ShieldCheck className="h-4.5 w-4.5 text-primary" />
            <span>Securely verified by Antigravity AI</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50/50 flex flex-col">
      {/* Top Header */}
      <header className="border-b border-slate-100 bg-white/80 backdrop-blur sticky top-0 z-30 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Bot className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-slate-900 leading-none">{data.session.title}</h1>
            <p className="text-[10px] text-slate-400 mt-1 font-medium">Shared from bot: {data.session.bot_name}</p>
          </div>
        </div>
        
        <div className="flex items-center gap-1.5 text-[10px] text-slate-500 font-semibold bg-slate-100 px-3 py-1 rounded-full">
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
          <span>Shared Snapshot</span>
        </div>
      </header>

      {/* Main chat layout */}
      <main className="flex-1 max-w-3xl w-full mx-auto px-4 py-8 space-y-6">
        {data.messages.map((m) => {
          const time = new Date(m.created_at).toLocaleTimeString(undefined, {
            hour: 'numeric',
            minute: '2-digit'
          });

          return (
            <div key={m.id} className="space-y-4">
              {/* User Msg */}
              {m.user_message && (
                <div className="flex justify-end gap-3">
                  <div className="max-w-[80%] bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-4 py-2.5 text-xs shadow-md leading-relaxed">
                    <p className="whitespace-pre-wrap">{m.user_message}</p>
                    <p className="text-right mt-1 text-[8px] opacity-75">{time}</p>
                  </div>
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/20 text-primary font-bold text-2xs uppercase">
                    U
                  </div>
                </div>
              )}

              {/* Bot Msg */}
              <div className="flex justify-start gap-3">
                <div className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-200 text-slate-800 font-bold text-2xs uppercase">
                  AI
                </div>
                <div className="max-w-[80%] bg-white border border-slate-100 rounded-2xl rounded-tl-sm px-4 py-3 text-xs shadow-sm space-y-1 relative">
                  <p className="leading-relaxed text-slate-800 whitespace-pre-wrap">
                    {m.assistant_response || "..."}
                  </p>
                  <p className="text-right text-[8px] text-slate-400 mt-1.5 pt-1.5 border-t border-slate-50">{time}</p>
                </div>
              </div>
            </div>
          );
        })}
      </main>

      {/* Footer banner */}
      <footer className="border-t border-slate-100 bg-white py-6 text-center text-2xs text-slate-400 font-medium">
        Powered by Antigravity AI SaaS Chatbot Console &copy; {new Date().getFullYear()}
      </footer>
    </div>
  );
}
