"use client";

import { useEffect, useState } from "react";
import { Copy, Check, MessageSquare, Bot, HelpCircle, Send, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useToastStore } from "@/store/toast-store";
import { API_BASE_URL } from "@/services/api";
import type { Bot as BotType, WidgetConfig } from "@/types/bot";
import { buildWidgetScriptSnippet, resolveWidgetBaseUrl } from "@/lib/deployment-contract";

interface WidgetCustomizerProps {
  bot: BotType;
  onSave: (values: { widgetConfig: WidgetConfig; welcomeMessage: string; allowedOrigins: string[] }) => Promise<void>;
  saving: boolean;
}

export function WidgetCustomizer({ bot, onSave, saving }: WidgetCustomizerProps) {
  const showToast = useToastStore((state) => state.showToast);
  
  // Default widget configuration
  const [config, setConfig] = useState<WidgetConfig>({
    ...bot.widgetConfig,
    welcome_message: bot.welcomeMessage || bot.widgetConfig.welcome_message,
  });
  const [allowedOriginsText, setAllowedOriginsText] = useState(bot.allowedOrigins.join("\n"));

  // Load bot's existing config
  useEffect(() => {
    setConfig({
      ...bot.widgetConfig,
      welcome_message: bot.welcomeMessage || bot.widgetConfig.welcome_message,
    });
    setAllowedOriginsText(bot.allowedOrigins.join("\n"));
  }, [bot]);

  const updateField = (key: keyof WidgetConfig, value: string) => {
    setConfig((curr) => ({
      ...curr,
      [key]: value,
    }));
  };

  // Preview chatbot session state
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewMessages, setPreviewMessages] = useState<Array<{ role: "user" | "assistant"; content: string }>>([]);
  const [previewInput, setPreviewInput] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewSession, setPreviewSession] = useState<{ session_id: string; session_token: string } | null>(null);
  const [copied, setCopied] = useState(false);

  // Initialize preview messages when widget opens
  useEffect(() => {
    if (previewOpen && previewMessages.length === 0) {
      setPreviewMessages([{ role: "assistant", content: config.welcome_message }]);
    }
  }, [previewOpen, config.welcome_message]);

  const handlePreviewSend = async () => {
    if (!previewInput.trim() || previewLoading) return;
    const userMsg = previewInput.trim();
    setPreviewMessages((curr) => [...curr, { role: "user", content: userMsg }]);
    setPreviewInput("");
    setPreviewLoading(true);

    try {
      let activeSession = previewSession;
      if (!activeSession) {
        const sessionResponse = await fetch(API_BASE_URL + "/public/widget/" + bot.id + "/session", {
          method: "POST",
        });
        if (!sessionResponse.ok) {
          throw new Error("Preview is not authorized for this origin. Add this dashboard origin to the allowed list.");
        }
        activeSession = (await sessionResponse.json()) as { session_id: string; session_token: string };
        setPreviewSession(activeSession);
      }
      const history = previewMessages.map((msg) => ({
        role: msg.role,
        content: msg.content,
      }));

      const res = await fetch(`${API_BASE_URL}/public/chat/${bot.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: activeSession.session_id,
          session_token: activeSession.session_token,
          turn_id: crypto.randomUUID(),
          message: userMsg,
          history,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setPreviewMessages((curr) => [...curr, { role: "assistant", content: data.reply }]);
      } else {
        setPreviewMessages((curr) => [...curr, { role: "assistant", content: "Error fetching bot reply." }]);
      }
    } catch {
      setPreviewMessages((curr) => [...curr, { role: "assistant", content: "Error communicating with chatbot." }]);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleSave = async () => {
    try {
      await onSave({
        widgetConfig: config,
        welcomeMessage: config.welcome_message,
        allowedOrigins: allowedOriginsText
          .split(/\r?\n/)
          .map((origin) => origin.trim())
          .filter(Boolean),
      });
      showToast({
        title: "Widget configuration saved",
        description: "Your chatbot widget configuration has been updated successfully.",
        variant: "success",
      });
    } catch (error) {
      showToast({
        title: "Failed to save configuration",
        description: error instanceof Error ? error.message : "There was an error updating your widget configuration.",
        variant: "error",
      });
    }
  };

  const runtimeOrigin = typeof window !== "undefined" ? window.location.origin : "";
  const widgetHost = resolveWidgetBaseUrl(process.env.NEXT_PUBLIC_APP_URL, runtimeOrigin);
  const apiBaseUrl = API_BASE_URL.replace(/\/$/, "");
  const embedCode = buildWidgetScriptSnippet(widgetHost, apiBaseUrl, bot.id);

  const copyEmbed = async () => {
    try {
      await navigator.clipboard.writeText(embedCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      showToast({
        title: "Copied!",
        description: "Widget embed snippet copied to clipboard.",
        variant: "success",
      });
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
      
      {/* Settings Form Panel */}
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Widget customizer</CardTitle>
            <CardDescription>
              Style the chat window, pick brand colors, and edit launcher features for your bot widget.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-2 text-sm">
                <span className="font-medium text-foreground">Welcome message</span>
                <input
                  type="text"
                  value={config.welcome_message}
                  onChange={(e) => updateField("welcome_message", e.target.value)}
                  className="h-10 w-full rounded-lg border border-input bg-background px-3 outline-none"
                />
              </label>

              <label className="space-y-2 text-sm">
                <span className="font-medium text-foreground">Launcher text</span>
                <input
                  type="text"
                  value={config.launcher_text}
                  onChange={(e) => updateField("launcher_text", e.target.value)}
                  className="h-10 w-full rounded-lg border border-input bg-background px-3 outline-none"
                />
              </label>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-2 text-sm">
                <span className="font-medium text-foreground">Placeholder text</span>
                <input
                  type="text"
                  value={config.placeholder_text}
                  onChange={(e) => updateField("placeholder_text", e.target.value)}
                  className="h-10 w-full rounded-lg border border-input bg-background px-3 outline-none"
                />
              </label>

              <label className="space-y-2 text-sm">
                <span className="font-medium text-foreground">Position</span>
                <select
                  value={config.position}
                  onChange={(e) => updateField("position", e.target.value)}
                  className="h-10 w-full rounded-lg border border-input bg-background px-3 outline-none"
                >
                  <option value="bottom-right">Bottom right</option>
                  <option value="bottom-left">Bottom left</option>
                </select>
              </label>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <label className="space-y-2 text-sm">
                <span className="font-medium text-foreground">Primary color</span>
                <div className="flex gap-2">
                  <input
                    type="color"
                    value={config.primary_color}
                    onChange={(e) => updateField("primary_color", e.target.value)}
                    className="h-10 w-12 rounded border border-input p-0.5 cursor-pointer bg-background"
                  />
                  <input
                    type="text"
                    value={config.primary_color}
                    onChange={(e) => updateField("primary_color", e.target.value)}
                    className="h-10 w-full rounded-lg border border-input bg-background px-2 text-xs outline-none"
                  />
                </div>
              </label>

              <label className="space-y-2 text-sm">
                <span className="font-medium text-foreground">Accent color</span>
                <div className="flex gap-2">
                  <input
                    type="color"
                    value={config.accent_color}
                    onChange={(e) => updateField("accent_color", e.target.value)}
                    className="h-10 w-12 rounded border border-input p-0.5 cursor-pointer bg-background"
                  />
                  <input
                    type="text"
                    value={config.accent_color}
                    onChange={(e) => updateField("accent_color", e.target.value)}
                    className="h-10 w-full rounded-lg border border-input bg-background px-2 text-xs outline-none"
                  />
                </div>
              </label>

              <label className="space-y-2 text-sm">
                <span className="font-medium text-foreground">Launcher icon</span>
                <select
                  value={config.launcher_icon}
                  onChange={(e) => updateField("launcher_icon", e.target.value)}
                  className="h-10 w-full rounded-lg border border-input bg-background px-3 outline-none"
                >
                  <option value="message">Chat Bubble</option>
                  <option value="bot">Robot</option>
                  <option value="support">Help Question</option>
                </select>
              </label>
            </div>

            <div className="pt-2">
              <label className="mb-4 block space-y-2 text-sm">
                <span className="font-medium text-foreground">Allowed embed origins</span>
                <textarea
                  value={allowedOriginsText}
                  onChange={(event) => setAllowedOriginsText(event.target.value)}
                  rows={4}
                  placeholder={"https://www.example.com\nhttps://*.customer.example"}
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 font-mono text-xs outline-none"
                />
                <span className="block text-xs text-muted-foreground">
                  One complete origin per line. Scheme and non-default port are enforced; use an explicit *. subdomain wildcard only when needed.
                </span>
              </label>
              <Button disabled={saving} onClick={handleSave} className="w-full sm:w-auto">
                Save Widget Configuration
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Integration snippet */}
        <Card>
          <CardHeader>
            <CardTitle>Embed Widget Script</CardTitle>
            <CardDescription>
              Copy this HTML script snippet and insert it before the closing &lt;/body&gt; tag of your site.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="relative rounded-lg bg-muted p-4 text-xs font-mono overflow-x-auto leading-relaxed border border-border">
              <pre>{embedCode}</pre>
              <button
                onClick={copyEmbed}
                className="absolute right-3 top-3 rounded border border-border bg-card p-1.5 hover:bg-muted text-muted-foreground"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Widget Preview Simulator Panel */}
      <div className="relative flex flex-col h-[520px] rounded-xl border border-border bg-slate-900/5 overflow-hidden shadow-inner">
        <div className="p-3 border-b border-border bg-card flex items-center justify-between text-xs font-bold text-muted-foreground">
          <span>LIVE PREVIEW SIMULATOR</span>
          <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
        </div>

        {/* Mock webpage body */}
        <div className="flex-1 p-6 relative flex flex-col justify-between bg-grid-slate-700/5">
          <div className="space-y-2">
            <h4 className="text-sm font-bold text-foreground opacity-60">My Brand Website</h4>
            <p className="text-2xs text-muted-foreground max-w-[200px]">
              This panel simulates how your chatbot widget floats and interacts on your customer-facing webpage.
            </p>
          </div>

          {/* Simulated Floating Chatbot Window */}
          {previewOpen && (
            <div
              className={`absolute bottom-16 ${
                config.position === "bottom-left" ? "left-4" : "right-4"
              } w-[300px] h-[380px] rounded-xl border border-border bg-card shadow-2xl flex flex-col overflow-hidden z-50 transition-all duration-300 transform scale-100 origin-bottom`}
              style={{ borderColor: config.primary_color }}
            >
              {/* Header */}
              <div
                className="p-3 flex items-center justify-between text-white shadow-sm"
                style={{ backgroundColor: config.primary_color }}
              >
                <div className="flex items-center gap-2">
                  <div className="h-6 w-6 rounded-full bg-white/20 flex items-center justify-center font-bold">
                    {config.launcher_icon === "bot" ? <Bot className="h-3.5 w-3.5" /> : <MessageSquare className="h-3.5 w-3.5" />}
                  </div>
                  <div>
                    <h5 className="text-2xs font-bold leading-none">{bot.name}</h5>
                    <span className="text-[9px] opacity-80 leading-none">Online</span>
                  </div>
                </div>
                <button onClick={() => setPreviewOpen(false)} className="hover:text-red-200">
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* Message Transcript */}
              <div className="flex-1 p-3 overflow-y-auto space-y-2 bg-muted/10 text-2xs">
                {previewMessages.map((msg, idx) => (
                  <div key={idx} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div
                      className={`px-3 py-1.5 rounded-lg max-w-[85%] ${
                        msg.role === "user"
                          ? "bg-primary text-primary-foreground rounded-tr-none"
                          : "bg-card border border-border text-foreground rounded-tl-none"
                      }`}
                      style={
                        msg.role === "user"
                          ? { backgroundColor: config.primary_color, color: "#fff" }
                          : undefined
                      }
                    >
                      {msg.content}
                    </div>
                  </div>
                ))}
                {previewLoading && (
                  <div className="flex justify-start">
                    <span className="text-[10px] text-muted-foreground animate-pulse">Typing...</span>
                  </div>
                )}
              </div>

              {/* Chat Input */}
              <div className="p-2 border-t border-border bg-card flex gap-1.5">
                <input
                  type="text"
                  placeholder={config.placeholder_text}
                  value={previewInput}
                  onChange={(e) => setPreviewInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handlePreviewSend();
                  }}
                  className="h-8 min-w-0 flex-1 border border-input rounded-md px-2 text-2xs outline-none bg-background focus:border-primary"
                />
                <Button
                  size="icon"
                  onClick={() => void handlePreviewSend()}
                  className="h-8 w-8 text-white"
                  style={{ backgroundColor: config.primary_color }}
                >
                  <Send className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          )}

          {/* Floating Launcher Button */}
          <button
            onClick={() => setPreviewOpen(!previewOpen)}
            className={`absolute bottom-4 ${
              config.position === "bottom-left" ? "left-4" : "right-4"
            } h-10 px-4 rounded-full text-white shadow-lg flex items-center gap-2 hover:scale-105 active:scale-95 transition-all z-40`}
            style={{ backgroundColor: config.primary_color }}
          >
            {config.launcher_icon === "bot" ? (
              <Bot className="h-4 w-4" />
            ) : config.launcher_icon === "support" ? (
              <HelpCircle className="h-4 w-4" />
            ) : (
              <MessageSquare className="h-4 w-4" />
            )}
            <span className="text-2xs font-semibold">{config.launcher_text}</span>
          </button>

        </div>
      </div>

    </div>
  );
}
