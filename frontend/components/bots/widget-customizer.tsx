"use client";

import { useEffect, useState } from "react";
import { Copy, Check, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useToastStore } from "@/store/toast-store";
import { API_BASE_URL } from "@/services/api";
import { experienceService } from "@/services/experience";
import type { ExperienceSettings } from "@/types/experience";
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

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);
  const [copied, setCopied] = useState(false);
  const [appearance, setAppearance] = useState<Pick<ExperienceSettings, "theme" | "font_family" | "density" | "corner_style">>({ theme: "light", font_family: "system", density: "comfortable", corner_style: "rounded" });
  const [appearanceReady, setAppearanceReady] = useState(false);
  const [appearanceError, setAppearanceError] = useState("");
  const [savingAppearance, setSavingAppearance] = useState(false);
  useEffect(() => {
    let active = true;
    setAppearanceReady(false);
    void experienceService.settings(bot.id).then((settings) => {
      if (active) { setAppearance({ theme: settings.theme, font_family: settings.font_family, density: settings.density, corner_style: settings.corner_style }); setAppearanceReady(true); setAppearanceError(""); }
    }).catch(() => { if (active) setAppearanceError("Appearance settings could not load. Refresh before changing them."); });
    return () => { active = false; };
  }, [bot.id]);

  const handleSave = async () => {
    setSavingAppearance(true);
    try {
      await onSave({
        widgetConfig: config,
        welcomeMessage: config.welcome_message,
        allowedOrigins: allowedOriginsText
          .split(/\r?\n/)
          .map((origin) => origin.trim())
          .filter(Boolean),
      });
      if (appearanceReady) {
        const latestSettings = await experienceService.settings(bot.id);
        await experienceService.saveSettings(bot.id, { ...latestSettings, ...appearance });
      }
      setPreviewKey((key) => key + 1);
      showToast({
        title: "Widget configuration saved",
        description: "Your chatbot widget configuration has been updated successfully.",
        variant: "success",
      });
    } catch (error) {
      showToast({
        title: "Some settings could not be saved",
        description: error instanceof Error ? error.message : "There was an error updating your widget configuration.",
        variant: "error",
      });
    } finally { setSavingAppearance(false); }
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

            <fieldset disabled={!appearanceReady} className="grid gap-4 border-t border-border pt-4 sm:grid-cols-2">
              <legend className="px-1 text-sm font-medium">Chat appearance</legend>
              {([
                { field: "theme", label: "Theme", options: [["light", "Light"], ["dark", "Dark"], ["auto", "Match visitor device"]] },
                { field: "font_family", label: "Font", options: [["system", "System"], ["inter", "Inter"], ["serif", "Serif"]] },
                { field: "density", label: "Spacing", options: [["comfortable", "Comfortable"], ["compact", "Compact"]] },
                { field: "corner_style", label: "Corners", options: [["rounded", "Rounded"], ["soft", "Soft"], ["square", "Square"]] },
              ] as const).map(({ field, label, options }) => <label className="space-y-2 text-sm" key={field}><span>{label}</span><select className="h-10 w-full rounded-lg border border-input bg-background px-3" value={appearance[field]} onChange={(event) => setAppearance((value) => ({ ...value, [field]: event.target.value }))}>{options.map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>)}
            </fieldset>
            {appearanceError && <p role="status" className="text-xs text-amber-700">{appearanceError}</p>}
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
              <Button disabled={saving || savingAppearance} onClick={handleSave} className="w-full sm:w-auto">
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
                aria-label={copied ? "Embed code copied" : "Copy embed code"}
                className="absolute right-3 top-3 rounded border border-border bg-card p-1.5 hover:bg-muted text-muted-foreground"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="h-fit overflow-hidden">
        <CardHeader>
          <div className="flex items-center justify-between"><CardTitle>Live widget</CardTitle>
            {previewOpen && <Button variant="ghost" size="icon" aria-label="Reload saved widget preview" onClick={() => setPreviewKey((key) => key + 1)}><RefreshCw size={15} /></Button>}
          </div>
          <CardDescription>Uses your real chat pipeline and saved settings. Sending questions uses your model allowance. Save changes to update this preview.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {previewOpen ? <iframe key={previewKey} title="Live chatbot preview" src={`/preview/chat/${encodeURIComponent(bot.id)}`} className="h-[650px] w-full border-0" allow="clipboard-write" /> : <div className="grid min-h-[420px] place-items-center p-6"><Button variant="outline" onClick={() => setPreviewOpen(true)}>Open live preview</Button></div>}
        </CardContent>
      </Card>

    </div>
  );
}
