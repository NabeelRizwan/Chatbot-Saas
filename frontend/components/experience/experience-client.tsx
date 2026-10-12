"use client";

import { useCallback, useEffect, useState } from "react";
import { BookOpenCheck, ContactRound, FlaskConical, Link2, Settings2, ShoppingBag } from "lucide-react";
import { experienceService } from "@/services/experience";
import { useAuthStore } from "@/store/auth-store";
import type { ExperienceSettings } from "@/types/experience";
import { FaqPanel } from "./faq-panel";
import { ProductPanel } from "./product-panel";
import { LeadsPanel } from "./leads-panel";
import { TestsPanel } from "./tests-panel";
import { SettingsPanel } from "./settings-panel";
import { IntegrationsPanel } from "./integrations-panel";
import { LoadError, LoadingState, messageOf, Notice, useExperienceAccess } from "./shared";

const sections = [
  { id: "settings", label: "Settings & sharing", icon: Settings2 },
  { id: "faqs", label: "Approved answers", icon: BookOpenCheck },
  { id: "products", label: "Product cards", icon: ShoppingBag },
  { id: "leads", label: "Leads & contacts", icon: ContactRound },
  { id: "integrations", label: "Booking & orders", icon: Link2 },
  { id: "tests", label: "Saved tests", icon: FlaskConical },
] as const;
type Section = (typeof sections)[number]["id"];

export function ExperienceClient({ botId }: { botId: string }) {
  const [section, setSection] = useState<Section>("settings");
  const [settings, setSettings] = useState<ExperienceSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const organization = useAuthStore((state) => state.selectedOrganizationId);
  const { canEdit, canViewLeads } = useExperienceAccess();
  const load = useCallback(async () => { setLoading(true); setError(""); try { setSettings(await experienceService.settings(botId)); } catch (reason) { setError(messageOf(reason)); } finally { setLoading(false); } }, [botId, organization]);
  useEffect(() => { void load(); }, [load]);
  if (loading) return <LoadingState />;
  if (!settings) return <LoadError error={error || "Could not load customer experience settings."} retry={() => void load()} />;
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-semibold">Customer experience</h2><p className="mt-1 text-sm text-muted-foreground">Helpful answers, customer actions and repeatable checks for this bot.</p></div><span className={`rounded-full border px-3 py-1 text-xs font-medium ${settings.enabled ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "border-border bg-muted text-muted-foreground"}`}>{settings.enabled ? "Features enabled" : "Features off"}</span></div>
    {!canEdit && <Notice>You have read-only access. An editor or workspace administrator can update these settings.</Notice>}
    <nav aria-label="Customer experience sections" className="flex flex-wrap gap-1 rounded-xl border border-border bg-muted/40 p-1.5">{sections.filter((item) => item.id !== "leads" || canViewLeads).map((item) => <button key={item.id} type="button" aria-current={section === item.id ? "page" : undefined} onClick={() => setSection(item.id)} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring ${section === item.id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:bg-card/70 hover:text-foreground"}`}><item.icon className="h-4 w-4" />{item.label}</button>)}</nav>
    <div key={`${botId}-${organization}`}>
      {section === "settings" && <SettingsPanel botId={botId} settings={settings} canEdit={canEdit} onSaved={setSettings} />}
      {section === "faqs" && <FaqPanel botId={botId} canEdit={canEdit} />}
      {section === "products" && <ProductPanel botId={botId} canEdit={canEdit} />}
      {section === "leads" && canViewLeads && <LeadsPanel botId={botId} canEdit={canEdit} />}
      {section === "integrations" && <IntegrationsPanel botId={botId} canEdit={canEdit} />}
      {section === "tests" && <TestsPanel botId={botId} canEdit={canEdit} />}
    </div>
  </div>;
}
