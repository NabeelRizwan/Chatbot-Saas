"use client";

import { cloneElement, isValidElement, useCallback, useEffect, useId, useState, type ReactElement, type ReactNode } from "react";
import { Loader2, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/store/auth-store";
import { getDocuments } from "@/services/knowledge-service";
import type { KnowledgeDocument } from "@/types/knowledge";

export const inputClass = "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
export const lines = (value: string) => [...new Set(value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean))];
export const messageOf = (error: unknown) => error instanceof Error ? error.message : "Something went wrong. Please try again.";
export const dateLabel = (value: string) => new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export function useExperienceAccess() {
  const role = useAuthStore((state) => state.activeOrganizationRole);
  const admin = useAuthStore((state) => state.user?.is_admin);
  return { canEdit: Boolean(admin || role === "owner" || role === "admin" || role === "editor"), canViewLeads: Boolean(admin || (role && role !== "viewer")) };
}

export function Field({ label, help, error, children }: { label: string; help?: string; error?: string; children: ReactNode }) {
  const id = useId();
  const control = isValidElement(children) ? cloneElement(children as ReactElement<Record<string, unknown>>, { id, "aria-describedby": help || error ? `${id}-description` : undefined, "aria-invalid": error ? true : undefined }) : children;
  return <div className="space-y-1.5 text-sm"><label htmlFor={id} className="block font-medium">{label}</label>{control}<div id={`${id}-description`}>{help && <p className="text-xs leading-relaxed text-muted-foreground">{help}</p>}{error && <p className="text-xs text-destructive" role="alert">{error}</p>}</div></div>;
}

export function Toggle({ label, description, checked, onChange, disabled }: { label: string; description?: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  const id = useId();
  return <label htmlFor={id} className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3 has-[:disabled]:cursor-default"><input id={id} type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} className="mt-0.5 h-4 w-4 rounded border-input text-primary focus:ring-ring" /><span><span className="block text-sm font-medium">{label}</span>{description && <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">{description}</span>}</span></label>;
}

export function Notice({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return <div role={error ? "alert" : "status"} className={`rounded-lg border p-3 text-sm leading-relaxed ${error ? "border-destructive/30 bg-destructive/5 text-destructive" : "border-border bg-muted/40 text-muted-foreground"}`}>{children}</div>;
}

export function LoadingState() { return <div role="status" className="flex items-center gap-2 p-6 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading…</div>; }
export function LoadError({ error, retry }: { error: string; retry: () => void }) { return <div className="space-y-3"><Notice error>{error}</Notice><Button variant="outline" onClick={retry}><RefreshCcw className="h-4 w-4" />Try again</Button></div>; }
export function EmptyState({ children }: { children: ReactNode }) { return <div className="rounded-xl border border-dashed border-border p-6 text-sm leading-relaxed text-muted-foreground">{children}</div>; }

export function SourcePicker({ botId, value, onChange, disabled }: { botId: string; value: number | null; onChange: (id: number | null) => void; disabled?: boolean }) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { let active = true; void getDocuments(botId).then((items) => { if (active) setDocuments(items); }).catch((reason: unknown) => { if (active) setError(messageOf(reason)); }); return () => { active = false; }; }, [botId]);
  return <Field label="Knowledge source (optional)" help="Link this entry to a source already uploaded to this bot." error={error}><select className={inputClass} value={value ?? ""} disabled={disabled} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}><option value="">No source selected</option>{value !== null && !documents.some((doc) => Number(doc.id) === value) && <option value={value}>Source {value} (not available)</option>}{documents.map((document) => <option key={document.id} value={document.id}>{document.filename}</option>)}</select></Field>;
}

export function useCollection<T>(botId: string, fetcher: (botId: string) => Promise<{ items: T[] }>) {
  const organization = useAuthStore((state) => state.selectedOrganizationId);
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => { setLoading(true); setError(""); try { const data = await fetcher(botId); setItems(data.items); } catch (reason) { setError(messageOf(reason)); } finally { setLoading(false); } }, [botId, fetcher, organization]);
  useEffect(() => { void load(); }, [load]);
  return { items, loading, error, load };
}
