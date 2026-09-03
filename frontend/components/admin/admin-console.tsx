"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { compatibleCredentials, configSnapshot } from "@/lib/admin-utils";
import { adminService, type AdminBot, type AdminOrganization, type Page, type PlatformKey, type ProviderOption } from "@/services/admin-service";

const inputClass = "h-10 w-full rounded-lg border border-input bg-background px-3 text-sm";
const providerNames: Record<string, string> = { gemini: "Gemini", openai: "OpenAI", claude: "Anthropic / Claude", grok: "xAI / Grok" };
const emptyPage = <T,>(): Page<T> => ({ items: [], total: 0, offset: 0, limit: 25 });
const errorMessage = (err: unknown) => err instanceof Error ? err.message : "Request failed. Please retry.";
const date = (value: string) => new Date(value).toLocaleDateString();

function Notice({ error, message }: { error?: string; message?: string }) {
  return <>{error && <p role="alert" className="rounded-lg border border-red-300 p-3 text-sm text-red-700 dark:text-red-300">{error}</p>}{message && <p role="status" className="rounded-lg bg-muted p-3 text-sm">{message}</p>}</>;
}

function Pagination({ page, onChange, busy = false }: { page: Page<unknown>; onChange: (offset: number) => void; busy?: boolean }) {
  return <div className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
    <span>{page.total ? `${page.offset + 1}–${Math.min(page.offset + page.limit, page.total)} of ${page.total}` : "No results"}</span>
    <div className="flex gap-2"><Button variant="outline" size="sm" disabled={busy || page.offset === 0} onClick={() => onChange(Math.max(0, page.offset - page.limit))}>Previous</Button><Button variant="outline" size="sm" disabled={busy || page.offset + page.limit >= page.total} onClick={() => onChange(page.offset + page.limit)}>Next</Button></div>
  </div>;
}

export function AdminOverview() {
  const [counts, setCounts] = useState<{ organizations: number; bots: number; enabled_credentials: number } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { adminService.overview().then(setCounts).catch((err: unknown) => setError(errorMessage(err))); }, []);
  return <div className="space-y-5"><Notice error={error} />
    <div className="grid gap-4 sm:grid-cols-3">{[["Organizations", counts?.organizations], ["Bots", counts?.bots], ["Enabled credentials", counts?.enabled_credentials]].map(([label, count]) => <Card key={String(label)}><CardHeader><CardDescription>{label}</CardDescription><CardTitle>{count ?? "…"}</CardTitle></CardHeader></Card>)}</div>
    <Card><CardHeader><CardTitle>Platform-owned credentials</CardTitle><CardDescription>Add a provider key once, then assign it by profile ID. New platform bots are assigned automatically to the oldest compatible profile with capacity. Profiles default to 2 bot slots, across customers and organizations.</CardDescription></CardHeader><CardContent><Button asChild><Link href="/admin/api-credentials">Manage API credentials</Link></Button></CardContent></Card>
  </div>;
}

export function AdminOrganizations() {
  const [page, setPage] = useState(emptyPage<AdminOrganization>);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    adminService.organizations({ search, offset, limit: 25 }).then((value) => { if (current) { setPage(value); setError(""); } }).catch((err: unknown) => { if (current) setError(errorMessage(err)); });
    return () => { current = false; };
  }, [search, offset]);
  return <Card><CardHeader><CardTitle>Organizations</CardTitle><CardDescription>Operational metadata only. No customer impersonation.</CardDescription></CardHeader><CardContent className="space-y-4">
    <label className="block text-sm">Search organizations<input className={inputClass} value={search} maxLength={200} onChange={(e) => { setSearch(e.target.value); setOffset(0); }} /></label><Notice error={error} />
    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b"><th className="p-3">Organization</th><th>ID</th><th>Bots</th><th>Created</th></tr></thead><tbody>{page.items.map((org) => <tr key={org.id} className="border-b"><td className="p-3"><Link className="text-primary underline" href={`/admin/bots?organization_id=${org.id}`}>{org.name}</Link></td><td>{org.id}</td><td>{org.bot_count}</td><td>{date(org.created_at)}</td></tr>)}</tbody></table></div>
    <Pagination page={page} onChange={setOffset} />
  </CardContent></Card>;
}

export function AdminCredentials() {
  const [page, setPage] = useState(emptyPage<PlatformKey>);
  const [providers, setProviders] = useState<ProviderOption[]>([]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [provider, setProvider] = useState("");
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");
  const [capacity, setCapacity] = useState("2");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    const value = await adminService.listPlatformKeys({ search, provider: filter || undefined, offset, limit: 25 });
    setPage(value);
  }, [search, filter, offset]);
  useEffect(() => { void load().catch((err: unknown) => setError(errorMessage(err))); }, [load]);
  useEffect(() => { adminService.providerOptions().then((value) => { setProviders(value.providers); setProvider(value.providers[0]?.id || ""); }).catch((err: unknown) => setError(errorMessage(err))); }, []);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setMessage("");
    try {
      await adminService.addPlatformKey({ provider, label: label.trim(), api_key: secret.trim(), max_bot_assignments: Number(capacity) });
      setSecret(""); setLabel(""); setCapacity("2");
      setMessage("Credential saved. The secret cannot be retrieved from this console.");
      await load();
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }

  async function action(key: PlatformKey, operation: "enable" | "disable" | "delete" | "rename" | "capacity") {
    if (operation === "delete" && !window.confirm(`Permanently delete credential #${key.id}? This cannot be undone.`)) return;
    if (operation === "disable" && !window.confirm(`Disable credential #${key.id}? Its ${key.assigned_bot_count} assigned bots will stop generating answers. Assignments are retained; no fallback or redistribution occurs.`)) return;
    const nextLabel = operation === "rename" ? window.prompt("New credential label (no secret)", key.label || "") : null;
    if (operation === "rename" && !nextLabel?.trim()) return;
    const nextCapacity = operation === "capacity" ? window.prompt(`Maximum bot assignments (currently ${key.assigned_bot_count} assigned)`, String(key.max_bot_assignments)) : null;
    if (operation === "capacity") {
      if (nextCapacity === null) return;
      if (!Number.isInteger(Number(nextCapacity)) || Number(nextCapacity) < 1 || Number(nextCapacity) > 2147483647) { setError("Enter a whole-number capacity of at least 1 (up to 2147483647)."); return; }
    }
    setBusy(true); setError(""); setMessage("");
    try {
      if (operation === "enable") await adminService.enableKey(key.id);
      if (operation === "disable") await adminService.disableKey(key.id);
      if (operation === "delete") await adminService.deleteKey(key.id);
      if (operation === "rename") await adminService.updateKeyLabel(key.id, nextLabel!.trim());
      if (operation === "capacity") await adminService.updateKeyCapacity(key.id, Number(nextCapacity), key.max_bot_assignments);
      setMessage("Credential updated."); await load();
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }

  return <div className="space-y-5"><Notice error={error} message={message} />
    <Card><CardHeader><CardTitle>Add API credential</CardTitle><CardDescription>Encrypted on the server with the existing platform encryption key. Paste the secret once; it is never returned after save.</CardDescription></CardHeader><CardContent>
      <form onSubmit={(e) => void add(e)} className="grid gap-4 md:grid-cols-3">
        <label className="text-sm">Provider<select className={inputClass} value={provider} onChange={(e) => setProvider(e.target.value)} required>{providers.map((item) => <option key={item.id} value={item.id}>{providerNames[item.id] || item.id}</option>)}</select></label>
        <label className="text-sm">Label<input className={inputClass} value={label} onChange={(e) => setLabel(e.target.value)} maxLength={200} required /></label>
        <label className="text-sm">API secret<input className={inputClass} type="password" autoComplete="new-password" value={secret} onChange={(e) => setSecret(e.target.value)} minLength={8} maxLength={8192} required /></label>
        <label className="text-sm">Maximum bot assignments<input className={inputClass} type="number" min={1} max={2147483647} step={1} value={capacity} onChange={(e) => setCapacity(e.target.value)} required /></label>
        <Button type="submit" disabled={busy || !Number.isInteger(Number(capacity)) || Number(capacity) < 1 || Number(capacity) > 2147483647 || !provider || !label.trim() || secret.trim().length < 8}>{busy ? "Saving…" : "Save credential"}</Button>
      </form>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>API credentials</CardTitle><CardDescription>Capacity is per bot, not per customer. To rotate: add a new profile, move each assigned bot, then delete the empty old profile. Disabling here does not revoke a key at its provider.</CardDescription></CardHeader><CardContent className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">Search labels<input className={inputClass} value={search} maxLength={200} onChange={(e) => { setSearch(e.target.value); setOffset(0); }} /></label><label className="text-sm">Filter provider<select className={inputClass} value={filter} onChange={(e) => { setFilter(e.target.value); setOffset(0); }}><option value="">All providers</option>{providers.map((item) => <option key={item.id} value={item.id}>{providerNames[item.id] || item.id}</option>)}</select></label></div>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b"><th className="p-3">Profile</th><th>Provider / status</th><th>Capacity / assigned bots</th><th>Dates</th><th>Actions</th></tr></thead><tbody>{page.items.map((key) => <tr key={key.id} className="border-b align-top">
        <td className="p-3">{key.label || "Unlabelled"}<div className="text-xs text-muted-foreground">ID {key.id}</div></td><td className="py-3">{providerNames[key.provider] || key.provider}<div>{key.status === "disabled" ? "Disabled" : "Enabled"}</div></td><td className="py-3">{key.assigned_bot_count} / {key.max_bot_assignments} bots · {key.remaining_capacity} slots free{key.status === "disabled" && " (disabled)"}<div className="space-y-1 text-xs">{key.assigned_bots.map((bot) => <div key={bot.id}>{bot.name} (#{bot.id}) · {bot.organization_name || "Legacy organization"} · {bot.customer_name} · {bot.provider} / {bot.model_name}</div>)}</div>{key.assigned_bot_count > 0 && <Link className="text-xs underline" href={`/admin/bots?credential_profile_id=${key.id}`}>View all assigned bots</Link>}</td><td className="py-3 text-xs">Created {date(key.created_at)}<br />Updated {date(key.updated_at)}</td>
        <td className="py-3"><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void action(key, "rename")}>Rename</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => void action(key, "capacity")}>Edit capacity</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => void action(key, key.status === "disabled" ? "enable" : "disable")}>{key.status === "disabled" ? "Enable" : "Disable"}</Button><Button size="sm" variant="outline" disabled={busy || key.assigned_bot_count > 0} onClick={() => void action(key, "delete")}>Delete</Button></div>{key.assigned_bot_count > 0 && <p className="mt-2 text-xs">Reassign or unassign all bots before deletion. Disabling keeps assignments.</p>}</td>
      </tr>)}</tbody></table></div><Pagination page={page} onChange={setOffset} busy={busy} />
    </CardContent></Card>
  </div>;
}

function BotEditor({ bot, providers, onSaved, onCancel }: { bot: AdminBot; providers: ProviderOption[]; onSaved: (bot: AdminBot) => void; onCancel: () => void }) {
  const [provider, setProvider] = useState(bot.provider);
  const [model, setModel] = useState(bot.model_name);
  const [profileId, setProfileId] = useState(bot.credential_profile_id);
  const [page, setPage] = useState(emptyPage<PlatformKey>);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    adminService.listPlatformKeys({ provider, offset, search, limit: 25, assignable_to_bot_id: bot.id }).then((value) => { if (current) setPage(value); }).catch((err: unknown) => { if (current) setError(errorMessage(err)); });
    return () => { current = false; };
  }, [provider, offset, search, bot.id]);
  const models = providers.find((option) => option.id === provider)?.models || [];
  const choices = compatibleCredentials(page.items, provider, bot.credential_profile_id);
  const chosenOffPage = profileId !== null && !choices.some((key) => key.id === profileId);

  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { onSaved(await adminService.updateBotConfig(bot.id, { provider, model_name: model, credential_profile_id: profileId }, configSnapshot(bot))); }
    catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }

  return <Card><CardHeader><CardTitle>Generation settings: {bot.name}</CardTitle><CardDescription>Organization {bot.organization_name} · Bot #{bot.id}. Generation changes do not change embedding models or existing knowledge vectors.</CardDescription></CardHeader><CardContent>
    <Notice error={error} />
    {bot.usage_mode === "byo" ? <p className="text-sm">This bot uses customer BYOK. Its owner must switch to platform mode in the customer settings before an admin can change its generation configuration.</p> : <form onSubmit={(e) => void save(e)} className="mt-4 grid gap-4 sm:grid-cols-2">
      <label className="text-sm">Generation provider<select className={inputClass} value={provider} onChange={(e) => { setProvider(e.target.value); setModel(providers.find((p) => p.id === e.target.value)?.models[0] || ""); setProfileId(null); setOffset(0); }} required>{providers.map((p) => <option key={p.id} value={p.id}>{providerNames[p.id] || p.id}</option>)}</select></label>
      <label className="text-sm">Generation model<select className={inputClass} value={model} onChange={(e) => setModel(e.target.value)} required>{!models.includes(model) && <option value={model} disabled>{model} (not currently supported)</option>}{models.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <label className="text-sm">Find compatible credentials<input className={inputClass} value={search} maxLength={200} onChange={(e) => { setSearch(e.target.value); setOffset(0); }} /></label>
      <label className="text-sm">Credential profile<select className={inputClass} value={profileId ?? ""} onChange={(e) => setProfileId(e.target.value ? Number(e.target.value) : null)}><option value="">{provider !== bot.provider ? "Auto-allocate for new provider (if capacity exists)" : "Unassigned — generation unavailable"}</option>{chosenOffPage && <option value={profileId!}>Selected profile #{profileId} (reload/search to verify availability)</option>}{choices.map((key) => <option key={key.id} value={key.id}>{key.label || "Unlabelled"} (#{key.id}, {key.assigned_bot_count}/{key.max_bot_assignments} bots, {key.remaining_capacity} free)</option>)}</select></label>
      <div className="sm:col-span-2"><Pagination page={page} onChange={setOffset} busy={busy} /><p className="mb-3 text-xs text-muted-foreground">Only enabled, same-provider profiles with free capacity (or this bot’s current slot) are selectable. Moving this bot leaves other assignments unchanged. No compatible capacity means no generation; environment keys are not a fallback.</p><Button type="submit" disabled={busy || !models.includes(model)}>{busy ? "Saving…" : "Save generation settings"}</Button></div>
    </form>}
    <Button className="mt-3" variant="ghost" disabled={busy} onClick={onCancel}>Close settings</Button>
  </CardContent></Card>;
}

export function AdminBots() {
  const params = useSearchParams();
  const organizationId = Number(params.get("organization_id")) || undefined;
  const credentialProfileId = Number(params.get("credential_profile_id")) || undefined;
  const [providerFilter, setProviderFilter] = useState("");
  const [unassigned, setUnassigned] = useState(false);
  const [page, setPage] = useState(emptyPage<AdminBot>);
  const [providers, setProviders] = useState<ProviderOption[]>([]);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<AdminBot | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const load = useCallback(async () => setPage(await adminService.bots({ search, offset, limit: 25, organization_id: organizationId, credential_profile_id: credentialProfileId, provider: providerFilter || undefined, unassigned })), [search, offset, organizationId, credentialProfileId, providerFilter, unassigned]);
  useEffect(() => { void load().catch((err: unknown) => setError(errorMessage(err))); }, [load]);
  useEffect(() => { adminService.providerOptions().then((value) => setProviders(value.providers)).catch((err: unknown) => setError(errorMessage(err))); }, []);
  return <div className="space-y-5"><Notice error={error} message={message} />
    {selected && <BotEditor key={selected.id} bot={selected} providers={providers} onCancel={() => setSelected(null)} onSaved={() => { setSelected(null); setMessage("Generation settings saved."); void load().catch((err: unknown) => setError(errorMessage(err))); }} />}
    <Card><CardHeader><CardTitle>Bots</CardTitle><CardDescription>Search by bot, customer, or organization name.{organizationId && <> Filtered to organization #{organizationId}. <Link className="underline" href="/admin/bots">Show all</Link></>}{credentialProfileId && <> Profile #{credentialProfileId}. <Link className="underline" href="/admin/bots">Clear profile filter</Link></>}</CardDescription></CardHeader><CardContent className="space-y-4">
      <label className="block text-sm">Search bots or customers<input className={inputClass} value={search} maxLength={200} onChange={(e) => { setSearch(e.target.value); setOffset(0); }} /></label>
      <div className="flex flex-wrap items-center gap-4"><label className="text-sm">Filter generation provider<select className={inputClass} value={providerFilter} onChange={(e) => { setProviderFilter(e.target.value); setOffset(0); }}><option value="">All providers</option>{providers.map((p) => <option key={p.id} value={p.id}>{providerNames[p.id] || p.id}</option>)}</select></label><label className="text-sm"><input type="checkbox" checked={unassigned} onChange={(e) => { setUnassigned(e.target.checked); setOffset(0); }} /> Unassigned platform bots only</label></div>
      <Button variant="outline" size="sm" onClick={() => { setSelected(null); setError(""); void load().catch((err: unknown) => setError(errorMessage(err))); }}>Reload bots</Button>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b"><th className="p-3">Bot</th><th>Organization / customer</th><th>Generation</th><th>Credential</th><th>Action</th></tr></thead><tbody>{page.items.map((bot) => <tr key={bot.id} className="border-b align-top"><td className="p-3">{bot.name}<div className="text-xs text-muted-foreground">#{bot.id} · {bot.status}</div></td><td className="py-3">{bot.organization_name} (#{bot.organization_id})<div className="text-xs">{bot.customer_name}</div></td><td className="py-3">{providerNames[bot.provider] || bot.provider}<div className="text-xs">{bot.model_name}</div></td><td className="py-3">{bot.usage_mode === "byo" ? "Customer BYOK" : bot.credential_label || (bot.credential_profile_id ? `Profile #${bot.credential_profile_id}` : "Unassigned — generation unavailable")}<div className="text-xs">{bot.credential_status === "disabled" ? "Disabled — admin action required" : bot.credential_status ? "Enabled" : ""}{bot.credential_profile_id && <> · {bot.credential_assigned_bot_count}/{bot.credential_max_bot_assignments} bots · {bot.credential_remaining_capacity} free</>}</div></td><td className="py-3"><Button size="sm" variant="outline" disabled={!providers.length} onClick={() => { setMessage(""); setSelected(bot); }}>Configure</Button></td></tr>)}</tbody></table></div><Pagination page={page} onChange={setOffset} />
    </CardContent></Card>
  </div>;
}
