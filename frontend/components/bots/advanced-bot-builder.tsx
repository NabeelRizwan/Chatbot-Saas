"use client";

import { useState, useEffect } from "react";
import { 
  Bot, Settings, Database, Play, 
  ArrowLeft, ArrowRight, Save, Check,
  Globe, Shield, Copy, Send, X
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { KnowledgeBotClient } from "@/components/knowledge/knowledge-bot-client";
import { API_BASE_URL } from "@/services/api";
import { useAuthStore } from "@/store/auth-store";
import { useToastStore } from "@/store/toast-store";
import { useRouter } from "next/navigation";

interface AdvancedBotBuilderProps {
  mode: "create" | "edit";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  bot?: any;
  loading?: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onSubmit: (values: any, files?: File[]) => Promise<void>;
}

export function AdvancedBotBuilder({ mode, bot, loading = false, onSubmit }: AdvancedBotBuilderProps) {
  const router = useRouter();
  const accessToken = useAuthStore((state) => state.accessToken);
  const showToast = useToastStore((state) => state.showToast);

  const [step, setStep] = useState(1);
  
  // Step 1: Identity
  const [name, setName] = useState(bot?.name ?? "");
  const [description, setDescription] = useState(bot?.description ?? "");
  const [avatarUrl, setAvatarUrl] = useState(bot?.avatar_url ?? "");
  const [category, setCategory] = useState(bot?.category ?? "general");

  // Step 2: Purpose
  const [systemPrompt, setSystemPrompt] = useState(bot?.systemPrompt ?? bot?.system_prompt ?? "You are a helpful AI support assistant.");
  const [tone, setTone] = useState(bot?.tone ?? "neutral");
  const [creativity, setCreativity] = useState(0.7);
  const [welcomeMessage, setWelcomeMessage] = useState(bot?.welcomeMessage ?? bot?.welcome_message ?? "Hi, how can I help you today?");

  // Step 3: Knowledge Base (integrated inside Edit Mode)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  
  // Step 4: Configuration
  const [aiUsageMode, setAiUsageMode] = useState<"platform" | "byo">(bot?.providerApiKey || bot?.provider_api_key ? "byo" : "platform");
  const [provider, setProvider] = useState<"gemini" | "openai" | "claude" | "grok">(bot?.provider ?? "gemini");
  const [model, setModel] = useState(bot?.model ?? bot?.model_name ?? "gemini-2.5-flash");
  const [providerApiKey, setProviderApiKey] = useState("");
  const [deployTab, setDeployTab] = useState<"widget" | "iframe" | "react" | "api" | "wp" | "shopify">("widget");
  const [webSearch, setWebSearch] = useState(bot?.capabilities?.web_search ?? false);
  const [fileAnalysis, setFileAnalysis] = useState(bot?.capabilities?.file_analysis ?? true);

  // Step 5: Testing
  const [previewMessage, setPreviewMessage] = useState("");
  const [previewChat, setPreviewChat] = useState<{ role: "user" | "model"; text: string; latency?: number; model?: string; provider?: string; sources?: (string | { filename: string })[] }[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Step 6: Publish
  const [status, setStatus] = useState(bot?.status ?? "active");

  useEffect(() => {
    if (bot) {
      setName(bot.name ?? "");
      setDescription(bot.description ?? "");
      setAvatarUrl(bot.avatar_url ?? "");
      setCategory(bot.category ?? "general");
      setSystemPrompt(bot.systemPrompt ?? bot.system_prompt ?? "");
      setWelcomeMessage(bot.welcomeMessage ?? bot.welcome_message ?? "Hi, how can I help you today?");
      setTone(bot.tone ?? "neutral");
      setProvider(bot.provider ?? "gemini");
      setModel(bot.model ?? bot.model_name ?? "gemini-2.5-flash");
      setWebSearch(bot.capabilities?.web_search ?? false);
      setFileAnalysis(bot.capabilities?.file_analysis ?? true);
      setCreativity(bot.capabilities?.temperature ?? 0.7);
      setStatus(bot.status ?? "active");
      if (bot.provider_api_key || bot.providerApiKey) {
        setAiUsageMode("byo");
      } else {
        setAiUsageMode("platform");
      }
    }
  }, [bot]);

  useEffect(() => {
    if (!bot) {
      setModel(provider === "gemini" ? "gemini-2.5-flash" : "gpt-4.1-mini");
    }
  }, [provider, bot]);

  const handleNext = () => {
    if (step === 1 && !name.trim()) {
      showToast({ title: "Name required", description: "Please enter a name for the assistant.", variant: "error" });
      return;
    }
    setStep((prev) => Math.min(prev + 1, 6));
  };

  const handlePrev = () => setStep((prev) => Math.max(prev - 1, 1));

  const handleSave = async () => {
    if (aiUsageMode === "byo") {
      if (mode === "create" && (!providerApiKey || providerApiKey.trim().length < 12)) {
        showToast({ title: "Provider API key required", description: "Provider API key must be at least 12 characters.", variant: "error" });
        return;
      }
      if (mode === "edit" && providerApiKey && providerApiKey.trim().length < 12) {
        showToast({ title: "Invalid API key", description: "New provider API key must be at least 12 characters.", variant: "error" });
        return;
      }
    }

    const payload = {
      name: name.trim(),
      description: description.trim(),
      avatar_url: avatarUrl.trim(),
      category,
      systemPrompt: systemPrompt.trim(),
      welcomeMessage: welcomeMessage.trim(),
      provider,
      model,
      tone,
      status,
      ai_usage_mode: aiUsageMode,
      capabilities: {
        web_search: webSearch,
        file_analysis: fileAnalysis,
        temperature: creativity
      },
      ...(aiUsageMode === "byo" && providerApiKey.trim() ? { providerApiKey: providerApiKey.trim() } : {}),
      ...(aiUsageMode === "platform" ? { providerApiKey: "" } : {}) // Explicitly clear if platform managed
    };
    await onSubmit(payload, selectedFiles);
  };

  const handleClone = async () => {
    if (mode === "create" || !bot) return;
    try {
      const res = await fetch(`${API_BASE_URL}/bot/${bot.id}/clone`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${accessToken}`
        }
      });
      if (res.ok) {
        showToast({ title: "Assistant cloned", description: "Successfully created a duplicate assistant.", variant: "success" });
        router.push("/bots");
      }
    } catch (err) {
      console.error(err);
    }
  };

  const sendPreviewMessage = async () => {
    if (!previewMessage.trim() || !bot) return;
    const userMsg = previewMessage.trim();
    setPreviewMessage("");
    setPreviewChat((prev) => [...prev, { role: "user", text: userMsg }]);
    setPreviewLoading(true);

    try {
      const history = previewChat.map(item => ({
        role: item.role === "user" ? "user" : "assistant",
        content: item.text
      }));
      
      const res = await fetch(`${API_BASE_URL}/chat/${bot.id}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`
        },
        body: JSON.stringify({
          message: userMsg,
          history: history,
          api_key: "dummy-key"
        })
      });
      if (res.ok) {
        const json = await res.json();
        setPreviewChat((prev) => [
          ...prev, 
          { 
            role: "model", 
            text: json.reply,
            latency: json.latency_ms,
            model: json.model_name,
            provider: json.provider,
            sources: json.sources
          }
        ]);
      } else {
        const errorData = await res.json();
        setPreviewChat((prev) => [...prev, { role: "model", text: `Error: ${errorData.detail || 'Failed to get response'}` }]);
      }
    } catch (err) {
      console.error(err);
      setPreviewChat((prev) => [...prev, { role: "model", text: "Network error occurred." }]);
    } finally {
      setPreviewLoading(false);
    }
  };

  const widgetHost = (typeof window !== "undefined" ? window.location.origin : (process.env.NEXT_PUBLIC_APP_URL || "")).replace(/\/$/, "");
  const apiBaseUrl = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
  const widgetSnippet = `<script
  src="${widgetHost}/widget.js"
  data-api-base-url="${apiBaseUrl}"
  data-bot-id="${bot?.id || 'YOUR_BOT_ID'}"
></script>`;

  return (
    <div className="space-y-6">
      {/* Wizard Step Indicator */}
      <div className="relative flex items-center justify-between max-w-2xl mx-auto py-4">
        <div className="absolute left-0 right-0 top-1/2 h-0.5 bg-muted -translate-y-1/2 z-0" />
        {[1, 2, 3, 4, 5, 6].map((s) => {
          const active = step >= s;
          const current = step === s;
          const label = s === 1 ? "Identity" : s === 2 ? "Purpose" : s === 3 ? "Knowledge" : s === 4 ? "Config" : s === 5 ? "Testing" : "Publish";
          return (
            <div key={s} className="relative z-10 flex flex-col items-center gap-2">
              <button
                onClick={() => {
                  if (mode === "edit" || s < step) setStep(s);
                }}
                className={`h-8 w-8 rounded-full flex items-center justify-center font-bold text-xs border transition-all duration-300 ${
                  current ? "bg-primary text-primary-foreground border-primary scale-110 shadow-md" :
                  active ? "bg-primary/10 text-primary border-primary" : "bg-card text-muted-foreground border-border"
                }`}
              >
                {s < step ? <Check className="h-4 w-4" /> : s}
              </button>
              <span className={`text-[10px] font-bold uppercase tracking-wider ${active ? "text-primary" : "text-muted-foreground"}`}>{label}</span>
            </div>
          );
        })}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        {/* Step Content */}
        <div className="min-h-[400px]">
          {step === 1 && (
            <Card>
              <CardHeader>
                <CardTitle>Step 1: Assistant Identity</CardTitle>
                <CardDescription>Name your bot, provide an avatar, and describe what it does.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-4">
                  <div className="h-16 w-16 rounded-full bg-primary/10 text-primary flex items-center justify-center font-bold text-lg border border-primary/20 overflow-hidden shrink-0">
                    {avatarUrl ? <img src={avatarUrl} alt="Avatar" className="h-full w-full object-cover" /> : <Bot className="h-8 w-8" />}
                  </div>
                  <div className="space-y-1.5 flex-1">
                    <label className="text-xs font-bold text-muted-foreground">Avatar Image URL</label>
                    <input
                      value={avatarUrl}
                      onChange={(e) => setAvatarUrl(e.target.value)}
                      placeholder="https://example.com/avatar.png"
                      className="h-9 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none"
                    />
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="space-y-1.5 text-xs font-bold text-muted-foreground block">
                    <span>Assistant Name</span>
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="Customer Support Assistant"
                      className="h-10 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none"
                    />
                  </label>
                  <label className="space-y-1.5 text-xs font-bold text-muted-foreground block">
                    <span>Category</span>
                    <select
                      value={category}
                      onChange={(e) => setCategory(e.target.value)}
                      className="h-10 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none"
                    >
                      <option value="general">General Support</option>
                      <option value="sales">Sales Assistant</option>
                      <option value="marketing">Marketing Specialist</option>
                      <option value="hr">HR / Recruiting</option>
                    </select>
                  </label>
                </div>

                <label className="space-y-1.5 text-xs font-bold text-muted-foreground block">
                  <span>Description</span>
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Describe what this assistant is trained to help with..."
                    className="min-h-24 w-full rounded-lg border border-input bg-background px-3 py-2 text-xs outline-none"
                  />
                </label>
              </CardContent>
            </Card>
          )}

          {step === 2 && (
            <Card>
              <CardHeader>
                <CardTitle>Step 2: Purpose & Behavior</CardTitle>
                <CardDescription>Determine how the bot behaves, its tone of voice, and custom prompts.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="space-y-1.5 text-xs font-bold text-muted-foreground block">
                    <span>Personality Tone</span>
                    <select
                      value={tone}
                      onChange={(e) => setTone(e.target.value)}
                      className="h-10 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none"
                    >
                      <option value="professional">Professional / Formal</option>
                      <option value="friendly">Friendly / Casual</option>
                      <option value="empathetic">Empathetic / Warm</option>
                      <option value="humorous">Humorous / Witty</option>
                      <option value="neutral">Standard Neutral</option>
                    </select>
                  </label>
                  
                  <div className="space-y-1.5 text-xs font-bold text-muted-foreground">
                    <div className="flex justify-between">
                      <span>Creativity / Temperature</span>
                      <span>{creativity}</span>
                    </div>
                    <input
                      type="range"
                      min="0.1"
                      max="1.0"
                      step="0.05"
                      value={creativity}
                      onChange={(e) => setCreativity(parseFloat(e.target.value))}
                      className="w-full mt-2 accent-primary cursor-pointer"
                    />
                  </div>
                </div>

                <label className="space-y-1.5 text-xs font-bold text-muted-foreground block">
                  <span>Welcome Message</span>
                  <textarea
                    value={welcomeMessage}
                    onChange={(e) => setWelcomeMessage(e.target.value)}
                    placeholder="Hi, how can I help you today?"
                    className="min-h-20 w-full rounded-lg border border-input bg-background px-3 py-2 text-xs outline-none"
                  />
                </label>

                <label className="space-y-1.5 text-xs font-bold text-muted-foreground block">
                  <span>System Instructions / Prompt</span>
                  <textarea
                    value={systemPrompt}
                    onChange={(e) => setSystemPrompt(e.target.value)}
                    placeholder="You are an expert support assistant..."
                    className="min-h-48 w-full rounded-lg border border-input bg-background px-3 py-2 text-xs outline-none font-mono"
                  />
                </label>
              </CardContent>
            </Card>
          )}

          {step === 3 && (
            <Card>
              <CardHeader>
                <CardTitle>Step 3: Knowledge Base Setup</CardTitle>
                <CardDescription>Upload files or crawl URLs to index information for semantic RAG lookup.</CardDescription>
              </CardHeader>
              <CardContent>
                {mode === "create" ? (
                  <div className="space-y-4">
                    <div className="flex flex-col items-center justify-center p-8 text-center text-muted-foreground border border-dashed border-border rounded-lg bg-background">
                      <Database className="h-10 w-10 text-primary opacity-50 mb-3" />
                      <p className="text-sm font-semibold text-foreground">Initial Knowledge Sources</p>
                      <p className="text-xs max-w-sm mt-1 mb-4">
                        Select files now. They will be uploaded automatically once the assistant is created.
                      </p>
                      <label className="cursor-pointer">
                        <span className="bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-md text-sm font-medium">
                          Select Files
                        </span>
                        <input 
                          type="file" 
                          multiple 
                          className="hidden" 
                          accept=".pdf,.txt,.docx,.csv,.xlsx,.md"
                          onChange={(e) => {
                            if (e.target.files) {
                              setSelectedFiles(prev => [...prev, ...Array.from(e.target.files!)]);
                            }
                          }}
                        />
                      </label>
                    </div>
                    {selectedFiles.length > 0 && (
                      <div className="space-y-2 mt-4">
                        <span className="text-xs font-bold text-muted-foreground block">Selected Files to Upload</span>
                        {selectedFiles.map((f, i) => (
                          <div key={i} className="flex items-center justify-between p-2 text-sm border border-border rounded-md bg-muted/10">
                            <span className="truncate max-w-[200px]">{f.name}</span>
                            <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => setSelectedFiles(prev => prev.filter((_, idx) => idx !== i))}>
                              <X className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <KnowledgeBotClient botId={bot.id} />
                )}
              </CardContent>
            </Card>
          )}

          {step === 4 && (
            <Card>
              <CardHeader>
                <CardTitle>Step 4: Configuration</CardTitle>
                <CardDescription>Choose how AI models are billed and configure bot capabilities.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                
                {/* AI Usage Mode Selector */}
                <div className="space-y-3">
                  <span className="block text-xs font-bold text-muted-foreground">AI Usage Mode</span>
                  <div className="grid sm:grid-cols-2 gap-3">
                    <div 
                      onClick={() => setAiUsageMode("platform")}
                      className={`cursor-pointer rounded-lg border-2 p-4 transition-all ${aiUsageMode === "platform" ? "border-primary bg-primary/5" : "border-border hover:border-primary/40 bg-card"}`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <Shield className={`h-4 w-4 ${aiUsageMode === "platform" ? "text-primary" : "text-muted-foreground"}`} />
                        <span className="text-sm font-bold text-foreground">Platform Managed</span>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        A dedicated API key from the platform pool is allocated exclusively to this bot.
                        Keys are encrypted at rest and never shared between bots.
                      </p>
                      {aiUsageMode === "platform" && (
                        <div className="mt-2 flex items-center gap-1.5 text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold">
                          <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
                          Dedicated key — encrypted at rest — 1:1 allocation
                        </div>
                      )}
                    </div>

                    <div 
                      onClick={() => setAiUsageMode("byo")}
                      className={`cursor-pointer rounded-lg border-2 p-4 transition-all ${aiUsageMode === "byo" ? "border-primary bg-primary/5" : "border-border hover:border-primary/40 bg-card"}`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <Settings className={`h-4 w-4 ${aiUsageMode === "byo" ? "text-primary" : "text-muted-foreground"}`} />
                        <span className="text-sm font-bold text-foreground">Bring Your Own Key</span>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        Use your own OpenAI or Gemini API key. Zero markup. You manage your own API billing directly.
                      </p>
                    </div>
                  </div>
                </div>

                {/* Provider and Model Selector */}
                <div className="grid gap-4 sm:grid-cols-2 pt-2 border-t border-border">
                  <label className="space-y-1.5 text-xs font-bold text-muted-foreground block">
                    <span>LLM Provider</span>
                    <select
                      value={provider}
                      onChange={(e) => setProvider(e.target.value as "gemini" | "openai" | "claude" | "grok")}
                      className="h-10 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none"
                    >
                      <option value="gemini">Google Gemini</option>
                      <option value="openai">OpenAI</option>
                      <option value="claude">Anthropic Claude</option>
                      <option value="grok">xAI Grok</option>
                    </select>
                  </label>
                  <label className="space-y-1.5 text-xs font-bold text-muted-foreground block">
                    <span>Model</span>
                    <select
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      className="h-10 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none"
                    >
                      {provider === "gemini" ? (
                        <>
                          <option value="gemini-2.5-flash">gemini-2.5-flash (Fast)</option>
                          <option value="gemini-1.5-pro">gemini-1.5-pro (Advanced)</option>
                        </>
                      ) : provider === "openai" ? (
                        <>
                          <option value="gpt-4.1-mini">gpt-4.1-mini (Fast)</option>
                          <option value="gpt-4.1">gpt-4.1 (Advanced)</option>
                        </>
                      ) : provider === "claude" ? (
                        <>
                          <option value="claude-3-5-sonnet">Claude 3.5 Sonnet (Advanced)</option>
                          <option value="claude-3-opus">Claude 3 Opus (Expert)</option>
                        </>
                      ) : (
                        <>
                          <option value="grok-2">Grok 2 (Advanced)</option>
                          <option value="grok-beta">Grok Beta (Fast)</option>
                        </>
                      )}
                    </select>
                  </label>
                </div>

                {/* API Key Input (if BYO mode) */}
                {aiUsageMode === "byo" && (
                  <div className="p-4 rounded-lg bg-muted/20 border border-border space-y-2">
                    <label className="space-y-1.5 text-xs font-bold text-muted-foreground block">
                      <span>{mode === "create" ? "Provider API Key" : "Rotate Provider API Key"}</span>
                      <input
                        type="password"
                        value={providerApiKey}
                        onChange={(e) => setProviderApiKey(e.target.value)}
                        placeholder={mode === "create" ? `Paste your ${provider === "gemini" ? "Gemini" : "OpenAI"} API key` : "Leave blank to keep current key"}
                        className="h-10 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none font-mono"
                      />
                      {mode === "edit" && bot?.apiKeyMasked && (
                        <span className="block text-[10px] text-muted-foreground mt-1">Current key: {bot.apiKeyMasked}</span>
                      )}
                    </label>
                  </div>
                )}

                {/* Capabilities */}
                <div className="space-y-3 pt-2 border-t border-border">
                   <span className="block text-xs font-bold text-muted-foreground">Extra Capabilities</span>
                   <div className="flex items-start gap-3 p-3 rounded-lg border border-border bg-muted/10 hover:bg-muted/30 transition-colors">
                     <input
                       type="checkbox"
                       id="webSearch"
                       checked={webSearch}
                       onChange={(e) => setWebSearch(e.target.checked)}
                       className="rounded border-input text-primary focus:ring-primary h-4 w-4 mt-0.5 cursor-pointer"
                     />
                     <label htmlFor="webSearch" className="text-xs font-semibold text-muted-foreground cursor-pointer select-none">
                       <span className="block text-foreground font-bold text-[13px]">Live Web Search</span>
                       Enables the bot to search public web queries when it lacks context in the knowledge base.
                     </label>
                   </div>
                   <div className="flex items-start gap-3 p-3 rounded-lg border border-border bg-muted/10 hover:bg-muted/30 transition-colors">
                     <input
                       type="checkbox"
                       id="fileAnalysis"
                       checked={fileAnalysis}
                       onChange={(e) => setFileAnalysis(e.target.checked)}
                       className="rounded border-input text-primary focus:ring-primary h-4 w-4 mt-0.5 cursor-pointer"
                     />
                     <label htmlFor="fileAnalysis" className="text-xs font-semibold text-muted-foreground cursor-pointer select-none">
                       <span className="block text-foreground font-bold text-[13px]">Advanced File Analysis</span>
                       Allows the assistant to extract structured charts, tables, and statistics from indexed documents.
                     </label>
                   </div>
                </div>

              </CardContent>
            </Card>
          )}

          {step === 5 && (
            <Card className="flex flex-col h-[500px]">
              <CardHeader className="py-4 border-b border-border bg-muted/5">
                <CardTitle className="text-sm font-bold uppercase tracking-wider flex items-center gap-2">
                  <Play className="h-4 w-4 text-primary fill-primary/10" /> Testing Playground
                </CardTitle>
                <CardDescription>
                  {mode === "create" ? "Save your assistant first to test it." : "Verify behavior, prompts, and knowledge hits before publishing."}
                </CardDescription>
              </CardHeader>
              
              {mode === "create" ? (
                  <div className="flex-1 flex flex-col items-center justify-center text-center text-muted-foreground p-8">
                    <Bot className="h-12 w-12 text-primary opacity-30 mb-4" />
                    <p className="text-sm font-semibold text-foreground">Assistant Needs to be Created</p>
                    <p className="text-xs max-w-sm mt-1">
                      You must save the assistant first before you can test it in the playground.
                    </p>
                  </div>
              ) : (
                <>
                  <CardContent className="flex-1 overflow-y-auto p-4 space-y-4 bg-muted/10">
                    {previewChat.length === 0 ? (
                      <div className="h-full flex flex-col items-center justify-center text-center text-muted-foreground">
                        <Bot className="h-10 w-10 text-primary opacity-30 mb-2 animate-bounce" />
                        <p className="text-xs font-semibold">Start a conversation</p>
                      </div>
                    ) : (
                      previewChat.map((item, idx) => (
                        <div key={idx} className={`flex ${item.role === "user" ? "justify-end" : "justify-start"}`}>
                          <div className={`max-w-[85%] rounded-xl px-4 py-2.5 text-[13px] leading-relaxed shadow-sm ${
                            item.role === "user" ? "bg-primary text-primary-foreground rounded-tr-sm" : "bg-card text-foreground rounded-tl-sm border border-border"
                          }`}>
                            <div>{item.text}</div>
                            {item.role === "model" && (item.latency || item.model) && (
                              <div className="mt-2 pt-1.5 border-t border-border/40 flex flex-wrap items-center gap-x-2 text-[10px] font-semibold text-muted-foreground">
                                {item.provider && <span className="capitalize">{item.provider}</span>}
                                {item.model && <span>{item.model}</span>}
                                {item.latency && <span>• {item.latency}ms</span>}
                              </div>
                            )}
                            {item.role === "model" && item.sources && item.sources.length > 0 && (
                              <div className="mt-2 pt-1 border-t border-border/40 text-[10px] text-muted-foreground">
                                <span className="font-bold block mb-1">Sources:</span>
                                <div className="flex flex-wrap gap-1">
                                  {item.sources.map((src: string | { filename: string }, idx: number) => {
                                    const name = typeof src === "string" ? src : (src as { filename: string }).filename;
                                    return (
                                      <span key={idx} className="bg-primary/5 text-primary border border-primary/10 rounded px-1.5 py-0.5 max-w-[150px] truncate">
                                        {name}
                                      </span>
                                    );
                                  })}
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      ))
                    )}
                    {previewLoading && (
                      <div className="flex justify-start">
                        <div className="bg-card text-muted-foreground border border-border rounded-xl rounded-tl-sm px-4 py-2.5 text-[13px] shadow-sm flex items-center gap-2">
                           <span className="flex gap-1">
                              <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{animationDelay: "0ms"}}></span>
                              <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{animationDelay: "150ms"}}></span>
                              <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{animationDelay: "300ms"}}></span>
                           </span>
                           Generating...
                        </div>
                      </div>
                    )}
                  </CardContent>
                  <div className="p-3 border-t border-border flex gap-2 bg-card">
                    <input
                      value={previewMessage}
                      onChange={(e) => setPreviewMessage(e.target.value)}
                      placeholder="Type a query to test..."
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void sendPreviewMessage();
                      }}
                      className="h-10 flex-1 rounded-lg border border-input px-3 text-sm outline-none focus:ring-1 focus:ring-primary/25"
                    />
                    <Button size="icon" className="h-10 w-10 rounded-lg" onClick={sendPreviewMessage} disabled={previewLoading || !previewMessage.trim()}>
                      <Send className="h-4 w-4" />
                    </Button>
                  </div>
                </>
              )}
            </Card>
          )}

          {step === 6 && (
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>Step 6: Publish & Deploy</CardTitle>
                  <CardDescription>Make your assistant live and embed it on your website.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  
                  {/* Status Toggle */}
                  <div className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/10">
                    <div className="space-y-1">
                      <span className="block text-sm font-bold text-foreground">Assistant Status</span>
                      <span className="text-xs text-muted-foreground block max-w-sm">Draft assistants will not respond to queries and are hidden from widget installations.</span>
                    </div>
                    <select
                      value={status}
                      onChange={(e) => setStatus(e.target.value)}
                      className={`h-9 rounded-lg border px-3 text-xs outline-none font-bold ${status === 'active' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'}`}
                    >
                      <option value="active">Active & Published</option>
                      <option value="draft">Save as Draft</option>
                    </select>
                  </div>

                  {/* Embed Code tabs */}
                  {mode === "edit" && (
                    <div className="space-y-4 pt-2">
                       <div className="flex border-b border-border overflow-x-auto text-xs font-semibold gap-2 pb-1.5">
                         <button onClick={() => setDeployTab("widget")} className={`px-2.5 py-1 rounded transition-colors ${deployTab === "widget" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>HTML Widget</button>
                         <button onClick={() => setDeployTab("iframe")} className={`px-2.5 py-1 rounded transition-colors ${deployTab === "iframe" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>Iframe</button>
                         <button onClick={() => setDeployTab("react")} className={`px-2.5 py-1 rounded transition-colors ${deployTab === "react" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>React / NextJS</button>
                         <button onClick={() => setDeployTab("api")} className={`px-2.5 py-1 rounded transition-colors ${deployTab === "api" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>REST API</button>
                         <button onClick={() => setDeployTab("wp")} className={`px-2.5 py-1 rounded transition-colors ${deployTab === "wp" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>WordPress</button>
                         <button onClick={() => setDeployTab("shopify")} className={`px-2.5 py-1 rounded transition-colors ${deployTab === "shopify" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>Shopify</button>
                       </div>

                       <div className="relative group">
                          {deployTab === "widget" && (
                            <>
                              <pre className="p-4 rounded-lg bg-zinc-950 text-zinc-50 text-[11px] overflow-x-auto font-mono leading-relaxed border border-zinc-800">
                                 {widgetSnippet}
                              </pre>
                              <Button 
                                 size="sm" 
                                 variant="secondary" 
                                 className="absolute top-2 right-2 h-7 text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
                                 onClick={() => {
                                    navigator.clipboard.writeText(widgetSnippet);
                                    showToast({title: "Copied!", description: "Widget snippet copied to clipboard.", variant: "success"});
                                 }}
                              >
                                 <Copy className="h-3 w-3 mr-1" /> Copy Code
                              </Button>
                            </>
                          )}

                          {deployTab === "iframe" && (
                            <>
                              <pre className="p-4 rounded-lg bg-zinc-950 text-zinc-50 text-[11px] overflow-x-auto font-mono leading-relaxed border border-zinc-800">
                                 {`<iframe src="${typeof window !== 'undefined' ? window.location.origin : ''}/public/chat/${bot?.id || 'BOT_ID'}" width="100%" height="600" style="border:none;"></iframe>`}
                              </pre>
                              <Button 
                                 size="sm" 
                                 variant="secondary" 
                                 className="absolute top-2 right-2 h-7 text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
                                 onClick={() => {
                                    navigator.clipboard.writeText(`<iframe src="${typeof window !== 'undefined' ? window.location.origin : ''}/public/chat/${bot?.id || 'BOT_ID'}" width="100%" height="600" style="border:none;"></iframe>`);
                                    showToast({title: "Copied!", description: "Iframe embed code copied to clipboard.", variant: "success"});
                                 }}
                              >
                                 <Copy className="h-3 w-3 mr-1" /> Copy Code
                              </Button>
                            </>
                          )}

                          {deployTab === "react" && (
                            <>
                              <pre className="p-4 rounded-lg bg-zinc-950 text-zinc-50 text-[10px] overflow-x-auto font-mono leading-relaxed border border-zinc-800">
{`import { useEffect } from 'react';

export default function ChatWidget() {
  useEffect(() => {
    const script = document.createElement('script');
    script.src = '${widgetHost}/widget.js';
    script.setAttribute('data-api-base-url', '${apiBaseUrl}');
    script.setAttribute('data-bot-id', '${bot?.id || 'BOT_ID'}');
    script.async = true;
    document.body.appendChild(script);
  }, []);

  return null;
}`}
                              </pre>
                              <Button 
                                 size="sm" 
                                 variant="secondary" 
                                 className="absolute top-2 right-2 h-7 text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
                                 onClick={() => {
                                    navigator.clipboard.writeText(`import { useEffect } from 'react';\n\nexport default function ChatWidget() {\n  useEffect(() => {\n    const script = document.createElement('script');\n    script.src = '${widgetHost}/widget.js';\n    script.setAttribute('data-api-base-url', '${apiBaseUrl}');\n    script.setAttribute('data-bot-id', '${bot?.id || 'BOT_ID'}');\n    script.async = true;\n    document.body.appendChild(script);\n  }, []);\n\n  return null;\n}`);
                                    showToast({title: "Copied!", description: "React component code copied to clipboard.", variant: "success"});
                                 }}
                              >
                                 <Copy className="h-3 w-3 mr-1" /> Copy Code
                              </Button>
                            </>
                          )}

                          {deployTab === "api" && (
                            <>
                              <pre className="p-4 rounded-lg bg-zinc-950 text-zinc-50 text-[11px] overflow-x-auto font-mono leading-relaxed border border-zinc-800">
{`curl -X POST ${typeof window !== 'undefined' ? window.location.origin : ''}/public/chat/${bot?.id || 'BOT_ID'} \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Hello assistant!"}'`}
                              </pre>
                              <Button 
                                 size="sm" 
                                 variant="secondary" 
                                 className="absolute top-2 right-2 h-7 text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
                                 onClick={() => {
                                    navigator.clipboard.writeText(`curl -X POST ${typeof window !== 'undefined' ? window.location.origin : ''}/public/chat/${bot?.id || 'BOT_ID'} \\\n  -H "Content-Type: application/json" \\\n  -d '{"message": "Hello assistant!"}'`);
                                    showToast({title: "Copied!", description: "CURL command copied to clipboard.", variant: "success"});
                                 }}
                              >
                                 <Copy className="h-3 w-3 mr-1" /> Copy Code
                              </Button>
                            </>
                          )}

                          {deployTab === "wp" && (
                            <div className="p-4 rounded-lg bg-zinc-950 text-zinc-300 text-xs border border-zinc-800 leading-relaxed font-sans">
                              <p className="font-bold text-zinc-50 mb-1.5">WordPress Integration Instructions:</p>
                              <ol className="list-decimal pl-4 space-y-1 text-zinc-400">
                                <li>Install and activate the <span className="text-primary font-bold">"Insert Headers and Footers"</span> plugin from your WordPress repository.</li>
                                <li>Navigate to Settings → Insert Headers and Footers in your dashboard.</li>
                                <li>Paste the <span className="underline cursor-pointer" onClick={() => setDeployTab("widget")}>HTML Widget snippet</span> into the "Scripts in Footer" box.</li>
                                <li>Save settings, and your AI assistant is active!</li>
                              </ol>
                            </div>
                          )}

                          {deployTab === "shopify" && (
                            <div className="p-4 rounded-lg bg-zinc-950 text-zinc-300 text-xs border border-zinc-800 leading-relaxed font-sans">
                              <p className="font-bold text-zinc-50 mb-1.5">Shopify Integration Instructions:</p>
                              <ol className="list-decimal pl-4 space-y-1 text-zinc-400">
                                <li>From your Shopify Admin, click Online Store → Themes.</li>
                                <li>Click Actions → Edit Code on your current active theme.</li>
                                <li>Under Layout, click <span className="font-bold text-primary">theme.liquid</span>.</li>
                                <li>Scroll down to the bottom and paste the <span className="underline cursor-pointer" onClick={() => setDeployTab("widget")}>HTML Widget snippet</span> right before the closing <span className="font-mono">&lt;/body&gt;</span> tag.</li>
                                <li>Click Save.</li>
                              </ol>
                            </div>
                          )}
                       </div>

                       <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between p-3 rounded-lg border border-border bg-muted/10 gap-3">
                         <div>
                           <span className="block text-xs font-bold text-foreground">Public Chat Link</span>
                           <span className="text-[10px] text-muted-foreground">Share a direct link to a hosted fullscreen version of your bot.</span>
                         </div>
                         <Button size="sm" variant="outline" className="h-8 text-xs font-bold gap-1 shrink-0" onClick={() => {
                           const shareLink = `${typeof window !== 'undefined' ? window.location.origin : ''}/public/chat/${bot?.id || 'BOT_ID'}`;
                           navigator.clipboard.writeText(shareLink);
                           showToast({title: "Copied link", description: "Public share link copied to clipboard.", variant: "success"});
                         }}>
                           <Globe className="h-3.5 w-3.5" /> Copy Share Link
                         </Button>
                       </div>
                    </div>
                  )}

                </CardContent>
              </Card>
            </div>
          )}

        </div>

        {/* Sidebar Summary & Nav */}
        <aside className="space-y-4">
          <Card className="sticky top-24">
            <CardHeader>
              <CardTitle>Summary</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2 text-xs font-medium text-muted-foreground">
                <div className="flex justify-between">
                  <span>Name:</span>
                  <span className="text-foreground font-bold">{name || "Untitled"}</span>
                </div>
                <div className="flex justify-between">
                  <span>Category:</span>
                  <span className="text-foreground uppercase text-[10px] font-bold">{category}</span>
                </div>
                <div className="flex justify-between">
                  <span>Mode:</span>
                  <span className="text-foreground font-bold capitalize">{aiUsageMode} Managed</span>
                </div>
                <div className="flex justify-between">
                  <span>Status:</span>
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                    status === "active" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"
                  }`}>{status}</span>
                </div>
              </div>

              <hr className="border-border" />

              <div className="flex flex-col gap-2">
                {step < 6 ? (
                  <Button className="w-full h-10 gap-1" onClick={handleNext}>
                    Next Step <ArrowRight className="h-4 w-4" />
                  </Button>
                ) : (
                  <Button className="w-full h-10 gap-1 bg-primary text-primary-foreground hover:bg-primary/95" onClick={handleSave} disabled={loading}>
                    <Save className="h-4 w-4" /> {mode === "create" ? "Create Assistant" : "Save Changes"}
                  </Button>
                )}
                {step > 1 && (
                  <Button variant="outline" className="w-full h-10 gap-1" onClick={handlePrev}>
                    <ArrowLeft className="h-4 w-4" /> Previous
                  </Button>
                )}
              </div>

              {mode === "edit" && bot && (
                <div className="pt-2 flex flex-col gap-2">
                  <Button variant="outline" className="w-full h-9 gap-1.5 text-xs text-muted-foreground hover:text-foreground" onClick={handleClone}>
                    <Copy className="h-3.5 w-3.5" /> Clone Assistant
                  </Button>
                  <Button variant="outline" className="w-full h-9 gap-1.5 text-xs text-muted-foreground hover:text-foreground" onClick={handleSave} disabled={loading}>
                    <Save className="h-3.5 w-3.5" /> Save Early
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
