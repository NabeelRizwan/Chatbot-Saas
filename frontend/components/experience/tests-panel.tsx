"use client";

import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { Pause, Pencil, Play, Plus, RefreshCcw, Save, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AnswerMarkdown, answerSourceLinks } from "@/components/chat/answer-markdown";
import { SourceLinks } from "@/components/chat/source-links";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { experienceService } from "@/services/experience";
import type { SavedQuestion, SavedQuestionRun } from "@/types/experience";
import { dateLabel, EmptyState, Field, inputClass, lines, LoadError, LoadingState, messageOf, Notice, Toggle, useCollection } from "./shared";

type QuestionFields = { question: string; expected_answer: string; required_phrases: string; forbidden_phrases: string; enabled: boolean };
const defaults: QuestionFields = { question: "", expected_answer: "", required_phrases: "", forbidden_phrases: "", enabled: true };
const statusLabel = { pending: "Waiting", running: "Running", passed_checks: "Phrase checks passed", needs_review: "Needs review", manual_review: "Manual review", error: "Error" };

export function TestsPanel({ botId, canEdit }: { botId: string; canEdit: boolean }) {
  const cases = useCollection(botId, experienceService.questions);
  const runs = useCollection(botId, experienceService.runs);
  const [editing, setEditing] = useState<number | undefined>();
  const [selected, setSelected] = useState<number[]>([]);
  const [activeRun, setActiveRun] = useState<SavedQuestionRun | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [runError, setRunError] = useState("");
  const [deleting, setDeleting] = useState<number | null>(null);
  const continueRef = useRef(false);
  const mountedRef = useRef(true);
  const busyRef = useRef(false);
  const stopPollingRef = useRef<(() => void) | null>(null);
  const form = useForm<QuestionFields>({ defaultValues: defaults });
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; continueRef.current = false; stopPollingRef.current?.(); }; }, []);
  function reset() { setEditing(undefined); setError(""); form.reset(defaults); }
  function edit(item: SavedQuestion) { setEditing(item.id); setError(""); form.reset({ ...item, required_phrases: item.required_phrases.join("\n"), forbidden_phrases: item.forbidden_phrases.join("\n") }); document.getElementById("question-editor")?.scrollIntoView({ behavior: "smooth", block: "start" }); setTimeout(() => form.setFocus("question"), 50); }
  async function save(values: QuestionFields) { setError(""); try { await experienceService.saveQuestion(botId, { ...values, question: values.question.trim(), expected_answer: values.expected_answer.trim(), required_phrases: lines(values.required_phrases), forbidden_phrases: lines(values.forbidden_phrases) }, editing); reset(); await cases.load(); } catch (reason) { setError(messageOf(reason)); } }
  async function remove(item: SavedQuestion) { if (!window.confirm(`Delete the saved question “${item.question}”? Existing test results remain available.`)) return; setDeleting(item.id); try { await experienceService.deleteQuestion(botId, item.id); setSelected((ids) => ids.filter((id) => id !== item.id)); if (editing === item.id) reset(); await cases.load(); } catch (reason) { setError(messageOf(reason)); } finally { setDeleting(null); } }
  async function execute(run: SavedQuestionRun, refresh = false) {
    continueRef.current = true; setRunning(true); setRunError(""); setActiveRun(run);
    let current = run;
    try {
      // Resume from authoritative saved state, including a worker still finishing
      // after navigation or an uncertain prior response. Never resubmit to poll.
      if (refresh) current = await experienceService.run(botId, current.id);
      if (mountedRef.current) setActiveRun(current);
      while (mountedRef.current && current.status !== "completed") {
        if (current.results.some((result) => result.status === "running")) {
          const keepPolling = await new Promise<boolean>((resolve) => {
            const timer = setTimeout(() => { stopPollingRef.current = null; resolve(true); }, 3000);
            stopPollingRef.current = () => { clearTimeout(timer); stopPollingRef.current = null; resolve(false); };
          });
          if (!keepPolling || !mountedRef.current) break;
          current = await experienceService.run(botId, current.id);
        } else {
          if (!continueRef.current) break;
          current = await experienceService.executeNext(botId, current.id);
        }
        if (mountedRef.current) setActiveRun(current);
      }
      if (mountedRef.current) await runs.load();
    } catch (reason) { if (mountedRef.current) setRunError(`${messageOf(reason)} Saved results are retained. Refresh the run before resuming.`); }
    finally { continueRef.current = false; busyRef.current = false; if (mountedRef.current) setRunning(false); }
  }
  async function start() {
    if (busyRef.current) return;
    const enabledIds = selected.filter((id) => cases.items.some((item) => item.id === id && item.enabled));
    if (!enabledIds.length || enabledIds.length > 30) { setRunError("Choose between one and thirty enabled questions."); return; }
    busyRef.current = true; setRunning(true); setRunError("");
    try { const run = await experienceService.createRun(botId, enabledIds); if (mountedRef.current) await execute(run); }
    catch (reason) { busyRef.current = false; if (mountedRef.current) { setRunning(false); setRunError(messageOf(reason)); } }
  }
  async function resume() { if (!activeRun || busyRef.current) return; busyRef.current = true; await execute(activeRun, true); }
  async function openRun(id: number) { setRunError(""); try { setActiveRun(await experienceService.run(botId, id)); } catch (reason) { setRunError(messageOf(reason)); } }
  async function cancelRun() { if (!activeRun || running || !window.confirm("Cancel the remaining questions in this run? Completed answers will be retained.")) return; setRunError(""); try { setActiveRun(await experienceService.cancelRun(botId, activeRun.id)); await runs.load(); } catch (reason) { setRunError(messageOf(reason)); } }
  const finished = activeRun?.results.filter((result) => result.status !== "pending" && result.status !== "running").length ?? 0;
  return <div className="space-y-6">
    <Notice>Tests use this bot’s current knowledge, settings and configured AI provider, and consume its API quota. Questions run one at a time in separate test conversations. Phrase checks identify missing or forbidden wording; they do not prove factual accuracy. Compare the answer with your reference before approving a change.</Notice>
    <div className="grid items-start gap-6 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>Saved questions</CardTitle><CardDescription>Keep representative customer questions to check after updates.</CardDescription></CardHeader><CardContent className="space-y-4">
        {cases.loading ? <LoadingState /> : cases.error ? <LoadError error={cases.error} retry={() => void cases.load()} /> : !cases.items.length ? <EmptyState>No saved questions yet. Add a question with its expected facts to begin.</EmptyState> : <>
          {canEdit && <div className="flex flex-wrap items-center gap-2"><Button variant="outline" size="sm" disabled={running} onClick={() => setSelected(cases.items.filter((item) => item.enabled).slice(0, 30).map((item) => item.id))}>Select up to 30</Button><Button variant="ghost" size="sm" disabled={running} onClick={() => setSelected([])}>Clear</Button><span className="text-xs text-muted-foreground">{selected.length} selected</span></div>}
          <div className="space-y-3">{cases.items.map((item) => <article key={item.id} className="rounded-xl border border-border p-3"><div className="flex items-start gap-3">{canEdit && <input type="checkbox" className="mt-1 h-4 w-4 rounded border-input text-primary" aria-label={`Select ${item.question}`} checked={selected.includes(item.id)} disabled={!item.enabled || running || (selected.length >= 30 && !selected.includes(item.id))} onChange={(event) => setSelected((ids) => event.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))} />}<div className="min-w-0 flex-1"><h3 className="text-sm font-medium break-words">{item.question}</h3><p className="mt-1 text-xs text-muted-foreground">{item.enabled ? `${item.required_phrases.length} required · ${item.forbidden_phrases.length} forbidden phrases` : "Disabled"}</p>{canEdit && <div className="mt-2 flex gap-2"><Button size="sm" variant="ghost" disabled={running} onClick={() => edit(item)}><Pencil className="h-3.5 w-3.5" />Edit</Button><Button size="sm" variant="ghost" disabled={running || deleting !== null} onClick={() => void remove(item)}><Trash2 className="h-3.5 w-3.5" />Delete</Button></div>}</div></div></article>)}</div>
          {canEdit && <Button onClick={() => void start()} disabled={running || !selected.length}><Play className="h-4 w-4" />Run {selected.length || "selected"} question{selected.length === 1 ? "" : "s"}</Button>}
        </>}
      </CardContent></Card>
      {canEdit && <Card id="question-editor" className="scroll-mt-6"><CardHeader><div className="flex justify-between gap-2"><CardTitle>{editing ? "Edit question" : "Add a test question"}</CardTitle>{editing && <Button size="sm" variant="ghost" disabled={running} onClick={reset}><Plus className="h-4 w-4" />New</Button>}</div></CardHeader><CardContent><form className="space-y-4" onSubmit={form.handleSubmit(save)}><fieldset disabled={form.formState.isSubmitting || running} className="space-y-4">
        <Field label="Customer question"><textarea rows={2} required minLength={3} maxLength={4000} className={inputClass} {...form.register("question", { required: true })} /></Field>
        <Field label="Expected answer or facts" help="Your reference for manual comparison. This text is not sent to the answering AI."><textarea rows={4} maxLength={10000} className={inputClass} {...form.register("expected_answer")} /></Field>
        <Field label="Required phrases" help="Optional. One phrase per line. Use short, essential facts rather than exact full sentences."><textarea rows={3} className={inputClass} {...form.register("required_phrases")} /></Field>
        <Field label="Forbidden phrases" help="Optional. One phrase per line. A match is flagged for review."><textarea rows={3} className={inputClass} {...form.register("forbidden_phrases")} /></Field>
        <Toggle label="Enabled" checked={form.watch("enabled")} onChange={(value) => form.setValue("enabled", value, { shouldDirty: true })} />
      </fieldset>{error && <Notice error>{error}</Notice>}<div className="flex gap-2"><Button type="submit" disabled={form.formState.isSubmitting || running}><Save className="h-4 w-4" />{form.formState.isSubmitting ? "Saving…" : "Save question"}</Button>{editing && <Button type="button" variant="outline" disabled={running} onClick={reset}>Cancel edit</Button>}</div></form></CardContent></Card>}
    </div>
    <Card><CardHeader><div className="flex flex-wrap items-center justify-between gap-3"><div><CardTitle>Test results</CardTitle><CardDescription className="mt-2">Saved answers, checks and total answer time for each run.</CardDescription></div><Button variant="outline" size="sm" disabled={running || runs.loading} onClick={() => { void runs.load(); if (activeRun) void openRun(activeRun.id); }}><RefreshCcw className="h-4 w-4" />Refresh</Button></div></CardHeader><CardContent className="space-y-4">
      {runError && <Notice error>{runError}</Notice>}
      {runs.error && <LoadError error={runs.error} retry={() => void runs.load()} />}
      {runs.items.length > 0 && <Field label="Choose a saved run"><select className={inputClass} value={activeRun?.id ?? ""} disabled={running} onChange={(event) => { if (event.target.value) void openRun(Number(event.target.value)); }}><option value="">Select a run</option>{runs.items.map((run) => <option key={run.id} value={run.id}>{dateLabel(run.created_at)} · {run.status} · Run {run.id}</option>)}</select></Field>}
      {!activeRun ? <EmptyState>Run saved questions or select a previous run to inspect the actual answers.</EmptyState> : <>
        <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm font-medium">Run {activeRun.id} · {finished} / {activeRun.results.length} finished</p>{canEdit && (running ? <Button variant="outline" onClick={() => { continueRef.current = false; }}><Pause className="h-4 w-4" />Pause after this question</Button> : activeRun.status !== "completed" && <div className="flex gap-2"><Button variant="outline" onClick={() => void resume()}><Play className="h-4 w-4" />Resume run</Button><Button variant="ghost" onClick={() => void cancelRun()}>Cancel remaining</Button></div>)}</div>
        {running && <Notice>The current answer will be saved before pausing. Leaving this tab pauses further questions; return to resume the saved run.</Notice>}
        <p className="text-xs text-muted-foreground">{activeRun.provider} · {activeRun.model} · {dateLabel(activeRun.created_at)}</p><progress className="h-2 w-full accent-primary" value={finished} max={Math.max(1, activeRun.results.length)} aria-label="Test run progress" />
        <div className="space-y-3">{activeRun.results.map((result) => <details key={result.id} className="rounded-xl border border-border p-4"><summary className="cursor-pointer text-sm font-medium"><span>{result.question}</span><span className={`ml-2 inline-block text-xs ${result.status === "needs_review" || result.status === "error" ? "text-destructive" : "text-muted-foreground"}`}>{statusLabel[result.status]}{result.latency_ms !== null ? ` · ${(result.latency_ms / 1000).toFixed(2)}s` : ""}</span></summary><div className="mt-4 grid gap-4 lg:grid-cols-2"><div><h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Actual answer</h4><AnswerMarkdown className="mt-2 text-sm" text={result.answer || (result.error ? "No answer returned." : "Not answered yet.")} allowedLinks={answerSourceLinks(result.sources)} /></div><div><h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Your reference</h4><p className="mt-2 whitespace-pre-wrap break-words text-sm">{result.expected_answer || "No reference supplied."}</p></div></div>{result.missing_phrases.length > 0 && <div className="mt-3"><Notice>Missing required phrases: {result.missing_phrases.join(" · ")}</Notice></div>}{result.forbidden_matches.length > 0 && <div className="mt-3"><Notice>Forbidden phrases found: {result.forbidden_matches.join(" · ")}</Notice></div>}{result.error && <div className="mt-3"><Notice error>{result.error}</Notice></div>}<SourceLinks sources={result.sources} className="mt-3 flex flex-wrap gap-3 text-xs" linkClassName="inline-flex items-center gap-1 text-primary hover:underline" /></details>)}</div>
      </>}
    </CardContent></Card>
  </div>;
}
