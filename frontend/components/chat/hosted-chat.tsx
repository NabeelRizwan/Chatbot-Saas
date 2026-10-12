"use client";

import { useEffect, useState } from "react";
import { API_BASE_URL } from "@/services/api";
import { getBot } from "@/services/bot-service";

type WidgetInstance = { destroy: () => void };
type WidgetWindow = Window & { ChatbotWidget?: { init: (options: Record<string, unknown>) => WidgetInstance } };

export function HostedChat({ botId, preview = false }: { botId: string; preview?: boolean }) {
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    let instance: WidgetInstance | undefined;
    const controller = new AbortController();
    async function start() {
      if (preview) {
        await getBot(botId);
      } else {
        const response = await fetch(`${API_BASE_URL}/public/widget/${encodeURIComponent(botId)}/experience`, { signal: controller.signal });
        if (!response.ok) throw new Error("This chatbot link is unavailable.");
        const settings = await response.json();
        if (!settings.enabled || !settings.hosted_chat_enabled) throw new Error("This chatbot link has not been enabled.");
      }
      if (!(window as WidgetWindow).ChatbotWidget) {
        await new Promise<void>((resolve, reject) => {
          const script = document.createElement("script"); script.src = "/widget.js"; script.onload = () => resolve(); script.onerror = () => reject(new Error("The chat could not load. Please refresh.")); document.head.appendChild(script);
        });
      }
      if (cancelled) return;
      instance = (window as WidgetWindow).ChatbotWidget!.init({ botId, apiBaseUrl: API_BASE_URL, standalone: true, rendererOrigin: window.location.origin, renderer: "assistant-ui" });
    }
    void start().catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "The chat is unavailable."); });
    return () => { cancelled = true; controller.abort(); instance?.destroy(); };
  }, [botId, preview]);
  return <main className="grid min-h-dvh place-items-center bg-slate-50 p-6"><p className="max-w-sm text-center text-sm text-slate-600" role="status">{error || "Connecting to your assistant…"}</p></main>;
}
