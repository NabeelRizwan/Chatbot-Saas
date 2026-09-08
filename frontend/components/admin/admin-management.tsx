"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AdminWorkspaceLink } from "@/components/admin/admin-workspace-link";
import { adminService, type AdminAudit, type AdminBot, type AdminPlan, type AdminUser, type Page } from "@/services/admin-service";
import { getUsage } from "@/services/billing-service";
import type { UsageSummary } from "@/types/billing";

const inputClass = "h-10 w-full rounded-lg border border-input bg-background px-3 text-sm";
const message = (error: unknown) => error instanceof Error ? error.message : "Request failed. Please retry.";
const emptyPage = <T,>(): Page<T> => ({ items: [], total: 0, offset: 0, limit: 25 });
function Pages({ page, change }: { page: Page<unknown>; change: (offset: number) => void }) {
  return <div className="flex items-center gap-3 pt-4 text-sm"><span>{page.total} total</span><Button variant="outline" disabled={!page.offset} onClick={() => change(Math.max(0, page.offset - page.limit))}>Previous</Button><Button variant="outline" disabled={page.offset + page.limit >= page.total} onClick={() => change(page.offset + page.limit)}>Next</Button></div>;
}

export function AdminUsers() {
  const [page, setPage] = useState(emptyPage<AdminUser>);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => setPage(await adminService.users({ search, offset, limit: 25 })), [search, offset]);
  useEffect(() => { void load().catch((err: unknown) => setError(message(err))); }, [load]);
  async function toggle(user: AdminUser) {
    if (!window.confirm(`${user.disabled ? "Enable" : "Disable"} ${user.email}?${user.disabled ? "" : " All their login sessions will be signed out."}`)) return;
    setBusy(true); setError("");
    try { await adminService.setUserDisabled(user, !user.disabled); await load(); }
    catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  }
  return <Card><CardHeader><CardTitle>Users</CardTitle><CardDescription>Manage account access. Team membership and roles are managed in each organization.</CardDescription></CardHeader><CardContent>
    {error && <p role="alert">{error}</p>}
    <label>Search users<input className={inputClass} value={search} onChange={(e) => { setSearch(e.target.value); setOffset(0); }} maxLength={200} /></label>
    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-3">User</th><th>Access</th><th>Status</th><th>Action</th></tr></thead><tbody>{page.items.map((user) => <tr key={user.id} className="border-b"><td className="p-3">{user.name}<div>{user.email} · #{user.id}</div></td><td>{user.is_admin ? "Platform admin" : "Customer"}</td><td>{user.disabled ? "Disabled" : "Enabled"}</td><td><Button variant="outline" disabled={busy} onClick={() => void toggle(user)}>{user.disabled ? "Enable" : "Disable"}</Button></td></tr>)}</tbody></table></div>
    <Pages page={page} change={setOffset} />
  </CardContent></Card>;
}

export function AdminKnowledge() {
  const [page, setPage] = useState(emptyPage<AdminBot>);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    adminService.bots({ search, offset, limit: 25 }).then((value) => { if (active) setPage(value); }).catch((err: unknown) => { if (active) setError(message(err)); });
    return () => { active = false; };
  }, [search, offset]);
  return <Card><CardHeader><CardTitle>Knowledge</CardTitle><CardDescription>Open any bot’s existing knowledge manager for sources, files, crawl pages, and job operations.</CardDescription></CardHeader><CardContent>
    {error && <p role="alert">{error}</p>}
    <label>Find a bot or organization<input className={inputClass} value={search} maxLength={200} onChange={(e) => { setSearch(e.target.value); setOffset(0); }} /></label>
    {page.items.map((bot) => <div className="flex justify-between gap-4 border-b py-4" key={bot.id}><span>{bot.name} · {bot.organization_name}</span><AdminWorkspaceLink organizationId={bot.organization_id} href={`/knowledge/${bot.id}`}>Manage knowledge</AdminWorkspaceLink></div>)}
    <Pages page={page} change={setOffset} />
  </CardContent></Card>;
}

const limitLabels: Record<string, string> = { max_bots: "Bots", max_documents: "Knowledge resources", monthly_messages: "Monthly messages", storage_bytes: "Logical storage (bytes)", team_members: "Team members" };

export function AdminPlans() {
  const params = useSearchParams();
  const organizationId = Number(params.get("organization_id")) || null;
  return <PlanManager key={organizationId ?? "all"} organizationId={organizationId} />;
}

function PlanManager({ organizationId }: { organizationId: number | null }) {
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [current, setCurrent] = useState<AdminPlan | null>(null);
  const [chosen, setChosen] = useState("");
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [editing, setEditing] = useState<AdminPlan | null>(null);
  const [limits, setLimits] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const load = useCallback(async () => {
    setPlans(await adminService.plans());
    if (organizationId) {
      const [plan, summary] = await Promise.all([adminService.organizationPlan(organizationId), getUsage(String(organizationId))]);
      setCurrent(plan); setChosen(String(plan.id)); setUsage(summary);
    }
  }, [organizationId]);
  useEffect(() => { void load().catch((err: unknown) => setError(message(err))); }, [load]);
  async function assign() {
    if (!organizationId || !current || !window.confirm(`Change only organization #${organizationId} to the selected plan?`)) return;
    setBusy(true); setError(""); setSuccess("");
    try { await adminService.assignPlan(organizationId, Number(chosen), current.id); await load(); setSuccess("Organization plan saved."); }
    catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  }
  async function saveLimits(event: React.FormEvent) {
    event.preventDefault();
    if (!editing || !window.confirm(`Change ${editing.name} limits for EVERY organization on this plan?`)) return;
    setBusy(true); setError(""); setSuccess("");
    try { await adminService.updatePlanLimits(editing, limits); setEditing(null); await load(); setSuccess("Plan limits saved."); }
    catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  }
  return <div className="space-y-5">
    {error && <p role="alert">{error}</p>}{success && <p role="status">{success}</p>}
    <Card><CardHeader><CardTitle>Plans / Usage</CardTitle><CardDescription>Assign existing plans to individual organizations or edit shared plan limits. Existing usage is retained; lowering a limit blocks future additions until usage fits.</CardDescription></CardHeader><CardContent className="space-y-4">
      <Link className="underline" href="/admin/organizations">Select an organization to manage its plan and usage</Link>
      {organizationId && <div className="space-y-3"><p>Organization #{organizationId} · Current plan: {current?.name ?? "Loading…"}</p><label>Assign plan<select className={inputClass} value={chosen} onChange={(e) => setChosen(e.target.value)}>{plans.filter((plan) => plan.active).map((plan) => <option key={plan.id} value={plan.id}>{plan.name}</option>)}</select></label><Button disabled={busy || !current || !chosen || chosen === String(current.id)} onClick={() => void assign()}>Save organization plan</Button>
        {usage && <div className="text-sm"><p>Knowledge: {Number(usage.usage.documents_used ?? 0) + Number(usage.usage.knowledge_resources_reserved ?? 0)} / {usage.limits.max_documents} · Messages: {usage.usage.messages_used ?? 0} / {usage.limits.monthly_messages}</p><AdminWorkspaceLink organizationId={organizationId} href="/usage">Full usage details</AdminWorkspaceLink></div>}
      </div>}
      {plans.map((plan) => <div key={plan.id} className="flex justify-between gap-4 border-b py-3"><div>{plan.name} ({plan.code}) · {plan.active ? "Active" : "Inactive"}<div className="text-sm">{Object.entries(limitLabels).map(([key, label]) => `${label}: ${plan.limits_json[key] ?? "Unlimited"}`).join(" · ")}</div></div><Button variant="outline" disabled={busy} onClick={() => { setEditing(plan); setLimits(Object.fromEntries(Object.keys(limitLabels).filter((key) => key in plan.limits_json).map((key) => [key, plan.limits_json[key]]))); }}>Edit limits</Button></div>)}
    </CardContent></Card>
    {editing && <Card><CardHeader><CardTitle>Edit {editing.name} limits</CardTitle><CardDescription>These limits apply to every organization assigned to this plan.</CardDescription></CardHeader><CardContent><form onSubmit={(event) => void saveLimits(event)} className="grid gap-4 sm:grid-cols-2">{Object.entries(limitLabels).map(([key, label]) => <label key={key}>{label}<input className={inputClass} type="number" min={1} max={Number.MAX_SAFE_INTEGER} step={1} required value={limits[key] ?? ""} onChange={(event) => setLimits({ ...limits, [key]: Number(event.target.value) })} /></label>)}<div className="flex gap-3"><Button disabled={busy} type="submit">Save shared limits</Button><Button variant="outline" type="button" disabled={busy} onClick={() => setEditing(null)}>Cancel</Button></div></form></CardContent></Card>}
  </div>;
}

export function AdminSystem() {
  const [page, setPage] = useState(emptyPage<AdminAudit>);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    adminService.auditLogs({ offset, limit: 25 }).then((value) => { if (active) setPage(value); }).catch((err: unknown) => { if (active) setError(message(err)); });
    return () => { active = false; };
  }, [offset]);
  return <Card><CardHeader><CardTitle>System / Audit</CardTitle><CardDescription>Recorded administrative actions. Credentials, authentication tokens, and system environment values are never displayed.</CardDescription></CardHeader><CardContent>
    {error && <p role="alert">{error}</p>}
    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-3">Time</th><th>Actor</th><th>Organization</th><th>Action</th></tr></thead><tbody>{page.items.map((entry) => <tr key={entry.id} className="border-b"><td className="p-3">{new Date(entry.created_at).toLocaleString()}</td><td>{entry.user_id ?? "Operator"}</td><td>{entry.organization_id ?? "Platform"}</td><td>{entry.action}</td></tr>)}</tbody></table></div><Pages page={page} change={setOffset} />
  </CardContent></Card>;
}
