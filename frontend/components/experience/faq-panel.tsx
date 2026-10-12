"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { CheckCircle2, Pencil, Plus, Save, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { experienceService } from "@/services/experience";
import { useToastStore } from "@/store/toast-store";
import type { ApprovedFaq } from "@/types/experience";
import { EmptyState, Field, inputClass, lines, LoadError, LoadingState, messageOf, Notice, SourcePicker, Toggle, useCollection } from "./shared";

type FaqFields = { question: string; answer: string; aliases: string; source_url: string; approved: boolean; enabled: boolean };
const defaults: FaqFields = { question: "", answer: "", aliases: "", source_url: "", approved: false, enabled: true };

export function FaqPanel({ botId, canEdit }: { botId: string; canEdit: boolean }) {
  const { items, loading, error, load } = useCollection(botId, experienceService.faqs);
  const [editing, setEditing] = useState<number | undefined>();
  const [source, setSource] = useState<number | null>(null);
  const [formError, setFormError] = useState("");
  const [deleting, setDeleting] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const showToast = useToastStore((state) => state.showToast);
  const form = useForm<FaqFields>({ defaultValues: defaults });
  const busy = form.formState.isSubmitting;

  function reset() { setEditing(undefined); setSource(null); setFormError(""); form.reset(defaults); }
  function edit(item: ApprovedFaq) {
    setEditing(item.id); setSource(item.source_document_id); setFormError("");
    form.reset({ ...item, aliases: item.aliases.join("\n"), source_url: item.source_url ?? "" });
    document.getElementById("faq-editor")?.scrollIntoView({ behavior: "smooth", block: "start" });
    setTimeout(() => form.setFocus("question"), 50);
  }
  async function save(values: FaqFields) {
    setFormError("");
    try {
      await experienceService.saveFaq(botId, { ...values, question: values.question.trim(), answer: values.answer.trim(), aliases: lines(values.aliases), source_url: values.source_url.trim() || null, source_document_id: source }, editing);
      showToast({ title: values.approved ? "Approved answer saved" : "Draft answer saved", variant: "success" }); reset(); await load();
    } catch (reason) { setFormError(messageOf(reason)); }
  }
  async function remove(item: ApprovedFaq) {
    if (!window.confirm(`Delete the approved-answer entry “${item.question}”?`)) return;
    setDeleting(item.id);
    try { await experienceService.deleteFaq(botId, item.id); if (editing === item.id) reset(); await load(); }
    catch (reason) { setFormError(messageOf(reason)); }
    finally { setDeleting(null); }
  }

  return <div className="grid items-start gap-6 xl:grid-cols-2">
    <Card><CardHeader><CardTitle>Approved answers</CardTitle><CardDescription>Answers you have reviewed for repeat questions. Other questions continue through the normal knowledge and AI flow.</CardDescription></CardHeader><CardContent className="space-y-4">
      <Notice>Only approved, enabled entries can answer a question. Add exact alternative wordings below; these entries do not guess which answer a similar question needs. Enable approved answers in Experience settings when ready.</Notice>
      <Field label="Find an answer"><input value={query} onChange={(event) => setQuery(event.target.value)} className={inputClass} type="search" placeholder="Search questions or answers" /></Field>
      {loading ? <LoadingState /> : error ? <LoadError error={error} retry={() => void load()} /> : !items.length ? <EmptyState>No approved answers yet. Add a question and a reviewed answer, then approve it when ready.</EmptyState> : <div className="space-y-3">{items.filter((item) => `${item.question} ${item.answer}`.toLowerCase().includes(query.toLowerCase())).map((item) => <article key={item.id} className="rounded-xl border border-border p-4">
        <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="min-w-0 flex-1 text-sm font-semibold break-words">{item.question}</h3><span className={`rounded-full px-2 py-1 text-xs ${item.approved && item.enabled ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "bg-muted text-muted-foreground"}`}>{!item.enabled ? "Disabled" : item.approved ? "Approved" : "Draft"}</span></div>
        <p className="mt-2 line-clamp-4 whitespace-pre-wrap break-words text-sm text-muted-foreground">{item.answer}</p>
        {(item.source_status === "changed" || item.source_status === "missing") && <div className="mt-3"><Notice>Source {item.source_status}. This answer is paused until you review and approve it again.</Notice></div>}
        {item.aliases.length > 0 && <p className="mt-2 text-xs text-muted-foreground">{item.aliases.length} alternative question{item.aliases.length === 1 ? "" : "s"}</p>}
        {canEdit && <div className="mt-3 flex gap-2"><Button size="sm" variant="outline" onClick={() => edit(item)}><Pencil className="h-3.5 w-3.5" />Edit</Button><Button size="sm" variant="ghost" disabled={deleting !== null} onClick={() => void remove(item)} aria-label={`Delete ${item.question}`}><Trash2 className="h-3.5 w-3.5" />Delete</Button></div>}
      </article>)}</div>}
    </CardContent></Card>
    {canEdit && <Card id="faq-editor" className="scroll-mt-6"><CardHeader><div className="flex items-center justify-between gap-2"><CardTitle>{editing ? "Edit answer" : "Add an answer"}</CardTitle>{editing && <Button variant="ghost" size="sm" onClick={reset}><Plus className="h-4 w-4" />New</Button>}</div><CardDescription>Write the answer exactly as visitors should receive it.</CardDescription></CardHeader><CardContent><form onSubmit={form.handleSubmit(save)} className="space-y-4">
      <fieldset disabled={busy} className="space-y-4">
        <Field label="Question" error={form.formState.errors.question?.message}><input className={inputClass} minLength={3} maxLength={1000} required {...form.register("question", { required: "Enter a question.", validate: (value) => value.trim().length >= 3 || "Enter a question with at least three characters." })} /></Field>
        <Field label="Approved answer" error={form.formState.errors.answer?.message}><textarea rows={7} className={inputClass} maxLength={10000} required {...form.register("answer", { required: "Enter an answer.", validate: (value) => Boolean(value.trim()) || "Enter an answer." })} /></Field>
        <Field label="Alternative question wordings" help="Optional. Up to 20 complete questions, one per line. Each wording receives this same answer." error={form.formState.errors.aliases?.message}><textarea rows={3} className={inputClass} {...form.register("aliases", { validate: (value) => (lines(value).length <= 20 && lines(value).every((line) => line.length <= 1000)) || "Use at most 20 alternatives, each up to 1,000 characters." })} /></Field>
        <SourcePicker botId={botId} value={source} onChange={setSource} />
        <Field label="Source link (optional)" help="The supporting page linked with this answer."><input type="url" className={inputClass} placeholder="https://example.com/help" {...form.register("source_url")} /></Field>
        <Toggle label="I have reviewed and approve this answer" description="Re-approving after a source change confirms that the answer is still current." checked={form.watch("approved")} onChange={(value) => form.setValue("approved", value, { shouldDirty: true })} />
        <Toggle label="Enabled" checked={form.watch("enabled")} onChange={(value) => form.setValue("enabled", value, { shouldDirty: true })} />
      </fieldset>
      {formError && <Notice error>{formError}</Notice>}
      <div className="flex flex-wrap gap-2"><Button type="submit" disabled={busy}>{form.watch("approved") ? <CheckCircle2 className="h-4 w-4" /> : <Save className="h-4 w-4" />}{busy ? "Saving…" : "Save answer"}</Button>{editing && <Button type="button" variant="outline" onClick={reset} disabled={busy}>Cancel edit</Button>}</div>
    </form></CardContent></Card>}
  </div>;
}
