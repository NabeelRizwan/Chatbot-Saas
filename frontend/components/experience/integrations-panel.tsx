"use client";

import { useCallback, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { CalendarDays, ExternalLink, Package, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { experienceService } from "@/services/experience";
import type { ExperienceIntegrations } from "@/types/experience";
import { Field, inputClass, LoadError, LoadingState, messageOf, Notice, Toggle } from "./shared";

export function IntegrationsPanel({ botId, canEdit }: { botId: string; canEdit: boolean }) {
  const [saved, setSaved] = useState<ExperienceIntegrations | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const form = useForm<ExperienceIntegrations>();
  const load = useCallback(async () => { setLoading(true); setError(""); try { const data = await experienceService.integrations(botId); setSaved(data); form.reset(data); } catch (reason) { setError(messageOf(reason)); } finally { setLoading(false); } }, [botId, form]);
  useEffect(() => { void load(); }, [load]);
  async function save(values: ExperienceIntegrations) { setError(""); setSuccess(false); try { const data = await experienceService.saveIntegrations(botId, values); setSaved(data); form.reset(data); setSuccess(true); } catch (reason) { setError(messageOf(reason)); } }
  if (loading) return <LoadingState />;
  if (!saved) return <LoadError error={error || "Could not load integrations."} retry={() => void load()} />;
  return <form onSubmit={form.handleSubmit(save)} className="space-y-4">
    <Notice>Connect your existing booking or customer-account page. Buttons open that provider’s page, where visitors book or sign in to view their orders. This does not create an appointment or expose order details inside the chat.</Notice>
    <fieldset disabled={!canEdit || form.formState.isSubmitting} className="grid items-start gap-6 xl:grid-cols-2">
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><CalendarDays className="h-5 w-5 text-primary" />Appointments</CardTitle><CardDescription>Visitors finish booking on your scheduling provider’s secure page.</CardDescription></CardHeader><CardContent className="space-y-4">
        <Field label="Booking provider"><select className={inputClass} {...form.register("booking.provider", { onChange: (event) => { if (event.target.value === "none") form.setValue("booking.enabled", false, { shouldDirty: true }); } })}><option value="none">Choose later</option><option value="calcom">Cal.com</option><option value="calendly">Calendly</option><option value="custom">Another booking page</option></select></Field>
        <Field label="Public booking page" help="Use your public HTTPS scheduling page, not a private dashboard or access token."><input type="url" pattern="https://.*" required={form.watch("booking.enabled")} placeholder="https://cal.com/your-team/consultation" className={inputClass} {...form.register("booking.url")} /></Field>
        <Field label="Button label"><input className={inputClass} maxLength={60} required={form.watch("booking.enabled")} {...form.register("booking.label")} /></Field>
        <Toggle label="Show booking button" disabled={form.watch("booking.provider") === "none"} checked={form.watch("booking.enabled")} onChange={(value) => form.setValue("booking.enabled", value, { shouldDirty: true })} />
        <ConnectionStatus enabled={saved.booking.enabled} url={saved.booking.url} />
      </CardContent></Card>
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><Package className="h-5 w-5 text-primary" />Order tracking</CardTitle><CardDescription>Send customers to their store’s secure order history or tracking page.</CardDescription></CardHeader><CardContent className="space-y-4">
        <Field label="Store provider"><select className={inputClass} {...form.register("orders.provider", { onChange: (event) => { if (event.target.value === "none") form.setValue("orders.enabled", false, { shouldDirty: true }); } })}><option value="none">Choose later</option><option value="shopify">Shopify</option><option value="custom">Another customer order page</option></select></Field>
        <Field label="Customer account or order page" help="Use the public sign-in destination for customers. Never paste a private per-order link, token or administrator URL."><input type="url" pattern="https://.*" required={form.watch("orders.enabled")} placeholder="https://your-store.com/account" className={inputClass} {...form.register("orders.url")} /></Field>
        <Field label="Button label"><input className={inputClass} maxLength={60} required={form.watch("orders.enabled")} {...form.register("orders.label")} /></Field>
        <Toggle label="Show order tracking button" disabled={form.watch("orders.provider") === "none"} checked={form.watch("orders.enabled")} onChange={(value) => form.setValue("orders.enabled", value, { shouldDirty: true })} />
        <ConnectionStatus enabled={saved.orders.enabled} url={saved.orders.url} />
      </CardContent></Card>
    </fieldset>
    {error && <Notice error>{error}</Notice>}{success && !form.formState.isDirty && <Notice>Integration links saved. Enable customer experience features in Settings to show active buttons.</Notice>}
    {canEdit && <Button type="submit" disabled={form.formState.isSubmitting || !form.formState.isDirty}><Save className="h-4 w-4" />{form.formState.isSubmitting ? "Saving…" : "Save integrations"}</Button>}
  </form>;
}

function ConnectionStatus({ enabled, url }: { enabled: boolean; url: string }) {
  const configured = enabled && /^https:\/\//i.test(url);
  return <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm"><p className="text-muted-foreground">{configured ? "Ready to open provider page" : "Not configured or disabled"}</p>{configured && <a href={url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1 text-primary hover:underline">Test saved link<ExternalLink className="h-3.5 w-3.5" /></a>}</div>;
}
