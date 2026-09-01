"use client";

import { Bot, MessageSquare, ShieldCheck } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { fetchSharedTranscript, type SharedTranscript } from "@/lib/public-share";
import { API_BASE_URL } from "@/services/api";

export default function PublicSharePage() {
  const params = useParams<{ token: string }>();
  const [data, setData] = useState<SharedTranscript | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const token = params.token;
    if (!token) {
      setError("This shared conversation link is invalid.");
      setLoading(false);
      return;
    }

    void fetchSharedTranscript(API_BASE_URL, token)
      .then((transcript) => {
        if (!cancelled) setData(transcript);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unable to load the transcript.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [params.token]);

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 p-4">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
          <p className="text-sm font-medium text-slate-500">Loading shared transcript...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 p-4">
        <div className="max-w-md rounded-2xl border border-border bg-card p-8 text-center shadow-md">
          <MessageSquare className="mx-auto mb-4 h-12 w-12 text-slate-300" />
          <h1 className="text-lg font-bold text-slate-900">Unavailable Transcript</h1>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            {error || "This shared conversation link is invalid or is no longer shared."}
          </p>
          <div className="mt-6 flex justify-center gap-2 text-[10px] text-muted-foreground">
            <ShieldCheck className="h-4 w-4 text-primary" />
            <span>Only the shared transcript is shown.</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-slate-50/50">
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-100 bg-white/80 px-6 py-4 backdrop-blur">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Bot className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-sm font-bold leading-none text-slate-900">{data.session.title}</h1>
            <p className="mt-1 text-[10px] font-medium text-slate-400">Shared from bot: {data.session.bot_name}</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-[10px] font-semibold text-slate-500">
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
          <span>Shared Snapshot</span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 space-y-6 px-4 py-8">
        {data.messages.map((message) => {
          const time = new Date(message.created_at).toLocaleTimeString(undefined, {
            hour: "numeric",
            minute: "2-digit",
          });
          return (
            <div key={message.id} className="space-y-4">
              {message.user_message && (
                <div className="flex justify-end gap-3">
                  <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-xs leading-relaxed text-primary-foreground shadow-md">
                    <p className="whitespace-pre-wrap">{message.user_message}</p>
                    <p className="mt-1 text-right text-[8px] opacity-75">{time}</p>
                  </div>
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/20 text-2xs font-bold uppercase text-primary">U</div>
                </div>
              )}
              <div className="flex justify-start gap-3">
                <div className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-200 text-2xs font-bold uppercase text-slate-800">AI</div>
                <div className="max-w-[80%] space-y-1 rounded-2xl rounded-tl-sm border border-slate-100 bg-white px-4 py-3 text-xs shadow-sm">
                  <p className="whitespace-pre-wrap leading-relaxed text-slate-800">{message.assistant_response || "..."}</p>
                  <p className="mt-1.5 border-t border-slate-50 pt-1.5 text-right text-[8px] text-slate-400">{time}</p>
                </div>
              </div>
            </div>
          );
        })}
      </main>

      <footer className="border-t border-slate-100 bg-white py-6 text-center text-2xs font-medium text-slate-400">
        Shared conversation snapshot
      </footer>
    </div>
  );
}
