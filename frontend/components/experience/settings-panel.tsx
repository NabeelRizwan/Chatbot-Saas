"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Copy, ExternalLink, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { experienceService } from "@/services/experience";
import { useToastStore } from "@/store/toast-store";
import type { ExperienceSettings } from "@/types/experience";
import { Field, inputClass, lines, messageOf, Notice, Toggle } from "./shared";

type SettingsFields = Omit<ExperienceSettings, "suggested_questions"> & { suggested_questions: string };
export function SettingsPanel({ botId, settings, canEdit, onSaved }: { botId: string; settings: ExperienceSettings; canEdit: boolean; onSaved: (settings: ExperienceSettings) => void }) {
  const [error, setError] = useState("");
  const [origin, setOrigin] = useState("");
  const toast = useToastStore((state) => state.showToast);
  const form = useForm<SettingsFields>({ defaultValues: { ...settings, suggested_questions: settings.suggested_questions.join("\n") } });
  useEffect(() => { setOrigin(window.location.origin); }, []);
  useEffect(() => { form.reset({ ...settings, suggested_questions: settings.suggested_questions.join("\n") }); }, [settings, form]);
  const hostedUrl = `${origin}/chat/${encodeURIComponent(botId)}`;
  async function save(values: SettingsFields) { setError(""); try { const saved = await experienceService.saveSettings(botId, { ...values, suggested_questions: lines(values.suggested_questions) }); onSaved(saved); toast({ title: "Experience settings saved", variant: "success" }); } catch (reason) { setError(messageOf(reason)); } }
  async function copyLink() { try { await navigator.clipboard.writeText(hostedUrl); toast({ title: "Chat link copied", variant: "success" }); } catch { setError("Could not copy automatically. Select and copy the link below."); } }
  return <div className="grid items-start gap-6 xl:grid-cols-[1.2fr_1fr]">
    <Card><CardHeader><CardTitle>Experience settings</CardTitle><CardDescription>Choose which customer features are available for this bot.</CardDescription></CardHeader><CardContent><form onSubmit={form.handleSubmit(save)} className="space-y-4"><fieldset disabled={!canEdit || form.formState.isSubmitting} className="space-y-4">
      <Toggle label="Enable customer experience features" description="The normal chat continues working when these features are off." checked={form.watch("enabled")} onChange={(value) => form.setValue("enabled", value, { shouldDirty: true })} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Toggle label="Approved FAQ answers" description="Serve your enabled, approved answers for matching questions." checked={form.watch("approved_faq_enabled")} onChange={(value) => form.setValue("approved_faq_enabled", value, { shouldDirty: true })} />
        <Toggle label="Contact form" description="Let visitors leave their details and a message." checked={form.watch("lead_form_enabled")} onChange={(value) => form.setValue("lead_form_enabled", value, { shouldDirty: true })} />
        <Toggle label="Product & service cards" description="Show your configured cards with matching answer sources." checked={form.watch("product_cards_enabled")} onChange={(value) => form.setValue("product_cards_enabled", value, { shouldDirty: true })} />
        <Toggle label="Standalone chat link" description="Let anyone with the link open this bot on a hosted chat page." checked={form.watch("hosted_chat_enabled")} onChange={(value) => form.setValue("hosted_chat_enabled", value, { shouldDirty: true })} />
      </div>
      <Field label="Suggested questions" help="Optional. One question per line, up to eight. Visitors can click these to start a chat." error={form.formState.errors.suggested_questions?.message}><textarea rows={5} className={inputClass} {...form.register("suggested_questions", { validate: (value) => (lines(value).length <= 8 && lines(value).every((line) => line.length <= 200)) || "Use at most eight questions, each up to 200 characters." })} /></Field>
      <Field label="Contact consent text" help="Visitors must agree to this before submitting their details. Use wording that accurately describes how you will contact them."><textarea rows={3} required={form.watch("lead_form_enabled")} minLength={10} maxLength={500} className={inputClass} {...form.register("lead_consent_text")} /></Field>
    </fieldset>{error && <Notice error>{error}</Notice>}{canEdit && <Button type="submit" disabled={form.formState.isSubmitting || !form.formState.isDirty}><Save className="h-4 w-4" />{form.formState.isSubmitting ? "Saving…" : "Save settings"}</Button>}</form></CardContent></Card>
    <Card><CardHeader><CardTitle>Share your chatbot</CardTitle><CardDescription>A standalone page uses this bot’s existing knowledge, model and settings.</CardDescription></CardHeader><CardContent className="space-y-4">
      <Notice>{settings.enabled && settings.hosted_chat_enabled ? "The standalone link is enabled. The bot must also be active before visitors can chat." : "Turn on customer experience features and the standalone chat link, then save settings to publish this page."}</Notice>
      <Field label="Chat link"><input readOnly value={hostedUrl} className={inputClass} onFocus={(event) => event.target.select()} /></Field><div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => void copyLink()} disabled={!origin}><Copy className="h-4 w-4" />Copy link</Button>{settings.enabled && settings.hosted_chat_enabled && <Button asChild variant="outline"><a href={hostedUrl} target="_blank" rel="noopener noreferrer"><ExternalLink className="h-4 w-4" />Open chat</a></Button>}</div>
    </CardContent></Card>
  </div>;
}
