"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCcw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { experienceService } from "@/services/experience";
import { useAuthStore } from "@/store/auth-store";
import type { ExperienceLead, LeadDetail, LeadStatus } from "@/types/experience";
import { dateLabel, EmptyState, inputClass, LoadError, LoadingState, messageOf, Notice } from "./shared";

export function LeadsPanel({ botId, canEdit }: { botId: string; canEdit: boolean }) {
  const [items, setItems] = useState<ExperienceLead[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [mutating, setMutating] = useState<number | null>(null);
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState<number | null>(null);
  const organization = useAuthStore((state) => state.selectedOrganizationId);
  const load = useCallback(async () => { setLoading(true); setError(""); try { const data = await experienceService.leads(botId, offset); setItems(data.items); setTotal(data.total); } catch (reason) { setError(messageOf(reason)); } finally { setLoading(false); } }, [botId, offset, organization]);
  useEffect(() => { void load(); }, [load]);
  async function updateStatus(lead: ExperienceLead, status: LeadStatus) { setMutating(lead.id); setError(""); try { await experienceService.updateLead(botId, lead.id, status); setItems((current) => current.map((item) => item.id === lead.id ? { ...item, status } : item)); } catch (reason) { setError(messageOf(reason)); } finally { setMutating(null); } }
  async function remove(lead: ExperienceLead) {
    if (!window.confirm(`Permanently delete contact ${lead.email} and their saved submissions?`)) return;
    setMutating(lead.id); setError("");
    try { await experienceService.deleteLead(botId, lead.id); if (items.length === 1 && offset > 0) setOffset(Math.max(0, offset - 25)); else await load(); } catch (reason) { setError(messageOf(reason)); } finally { setMutating(null); }
  }
  async function openDetail(lead: ExperienceLead) { if (detail?.id === lead.id) { setDetail(null); return; } setDetailLoading(lead.id); try { setDetail(await experienceService.lead(botId, lead.id)); } catch (reason) { setError(messageOf(reason)); } finally { setDetailLoading(null); } }
  return <Card><CardHeader><div className="flex flex-wrap items-center justify-between gap-3"><div><CardTitle>Leads & contacts</CardTitle><CardDescription className="mt-2">People who asked to be contacted through this bot.</CardDescription></div><Button variant="outline" size="sm" disabled={loading} onClick={() => void load()}><RefreshCcw className="h-4 w-4" />Refresh</Button></div></CardHeader><CardContent className="space-y-4">
    <Notice>Enable the contact form in Experience settings. Visitors choose whether to submit their details and consent to being contacted. Submissions are stored here; no automatic email is sent.</Notice>
    {loading ? <LoadingState /> : error ? <LoadError error={error} retry={() => void load()} /> : !items.length ? <EmptyState>No contacts yet. Submitted forms will appear here with their consent date.</EmptyState> : <>
      <p className="text-sm text-muted-foreground">{total} contact{total === 1 ? "" : "s"} · Showing {offset + 1}–{Math.min(offset + items.length, total)}</p>
      <div className="grid items-start gap-4 lg:grid-cols-2">{items.map((lead) => <article key={lead.id} className="space-y-3 rounded-xl border border-border p-4">
        <div><h3 className="font-semibold">{lead.name || "Contact"}</h3><a className="break-all text-sm text-primary hover:underline" href={"mailto:" + lead.email}>{lead.email}</a>{lead.phone && <p className="mt-1 text-sm text-muted-foreground">{lead.phone}</p>}</div>
        {lead.message && <p className="whitespace-pre-wrap break-words rounded-lg bg-muted/50 p-3 text-sm">{lead.message}</p>}
        <p className="text-xs text-muted-foreground">Consent recorded {dateLabel(lead.consent_at || lead.created_at)}</p>
        <div className="flex items-center justify-between gap-3"><label className="flex items-center gap-2 text-sm"><span>Status</span><select className={inputClass} value={lead.status} disabled={!canEdit || mutating !== null} onChange={(event) => void updateStatus(lead, event.target.value as LeadStatus)}><option value="new">New</option><option value="contacted">Contacted</option><option value="closed">Closed</option></select></label>{canEdit && <Button variant="ghost" size="icon" disabled={mutating !== null} aria-label={"Delete contact " + lead.email} onClick={() => void remove(lead)}><Trash2 className="h-4 w-4" /></Button>}</div>
        <Button variant="outline" size="sm" disabled={detailLoading !== null} aria-expanded={detail?.id === lead.id} onClick={() => void openDetail(lead)}>{detailLoading === lead.id ? "Loading…" : detail?.id === lead.id ? "Hide submissions" : "View submissions"}</Button>
        {detail?.id === lead.id && <div className="space-y-3">{detail.submissions.map((submission) => <div key={submission.id} className="rounded-lg bg-muted/40 p-3"><p className="text-xs text-muted-foreground">{dateLabel(submission.consent_at)} · {submission.name}{submission.phone ? " · " + submission.phone : ""}</p><p className="mt-2 whitespace-pre-wrap break-words text-sm">{submission.message || "No message included."}</p><p className="mt-2 text-xs text-muted-foreground">Agreed to: {submission.consent_text}</p></div>)}</div>}
      </article>)}</div>
      <div className="flex items-center justify-between gap-3"><Button variant="outline" disabled={offset === 0 || loading} onClick={() => { setDetail(null); setOffset(Math.max(0, offset - 25)); }}>Previous</Button><Button variant="outline" disabled={offset + 25 >= total || loading} onClick={() => { setDetail(null); setOffset(offset + 25); }}>Next</Button></div>
    </>}
  </CardContent></Card>;
}
