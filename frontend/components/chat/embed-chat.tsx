"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AssistantChat } from "./assistant-chat";
import type { BridgeCommand, ExperienceSnapshot } from "./experience-contract";

export function EmbedChat() {
  const bridge = useRef<{ origin: string; nonce: string } | null>(null);
  const [snapshot, setSnapshot] = useState<ExperienceSnapshot | null>(null);
  const command = useCallback((value: BridgeCommand) => {
    const connection = bridge.current;
    if (connection) window.parent.postMessage({ channel: "chatbot-assistant-ui-v1", nonce: connection.nonce, ...value }, connection.origin);
  }, []);
  useEffect(() => {
    const parameters = new URLSearchParams(window.location.hash.slice(1));
    const parentOrigin = parameters.get("parentOrigin");
    const nonce = parameters.get("nonce");
    if (!parentOrigin || !nonce || !/^[0-9a-f-]{36}$/i.test(nonce)) return;
    let origin: string;
    try { const parsed = new URL(parentOrigin); if (!["https:", "http:"].includes(parsed.protocol) || parsed.origin !== parentOrigin) return; origin = parsed.origin; } catch { return; }
    if (window.parent === window) return;
    bridge.current = { origin, nonce };
    const listener = (event: MessageEvent) => {
      if (event.source !== window.parent || event.origin !== origin || event.data?.channel !== "chatbot-assistant-ui-v1" || event.data.nonce !== nonce) return;
      if (event.data.action === "snapshot" && event.data.snapshot && Array.isArray(event.data.snapshot.messages)) setSnapshot(event.data.snapshot as ExperienceSnapshot);
      if (event.data.action === "focus") document.querySelector<HTMLTextAreaElement>("textarea[aria-label='Your message']")?.focus();
    };
    window.addEventListener("message", listener);
    command({ action: "ready" });
    const readyInterval = window.setInterval(() => command({ action: "ready" }), 2000);
    return () => { window.removeEventListener("message", listener); window.clearInterval(readyInterval); bridge.current = null; };
  }, [command]);
  return snapshot ? <AssistantChat snapshot={snapshot} command={command} /> : <main className="grid h-dvh place-items-center bg-white text-sm text-slate-500" role="status">Connecting to your assistant…</main>;
}
