"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiServiceError } from "@/services/api";
import { adminService, type AdminOrganization, type KnowledgePipeline, type OrganizationKnowledgePipeline } from "@/services/admin-service";

const labels: Record<KnowledgePipeline, string> = { og: "OG", rag2_improved: "RAG2 Improved" };

export function OrganizationPipelineEditor({ organization, onClose }: { organization: AdminOrganization; onClose: () => void }) {
  const [current, setCurrent] = useState<OrganizationKnowledgePipeline | null>(null);
  const [selected, setSelected] = useState<KnowledgePipeline | "">("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reloadRequired, setReloadRequired] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reload, setReload] = useState(0);
  const requestVersion = useRef(0);
  const savingRef = useRef(false);

  useEffect(() => {
    const version = ++requestVersion.current;
    // Each load belongs to this organization and editor instance. Late reads or
    // saves must not populate a different organization's editor after navigation.
    adminService.organizationKnowledgePipeline(organization.id).then((value) => {
      if (requestVersion.current !== version) return;
      setCurrent(value);
      setSelected(value.pipeline);
      setLoading(false);
    }).catch((err: unknown) => {
      if (requestVersion.current !== version) return;
      setError(err instanceof ApiServiceError && err.status === 403
        ? "Platform administrator access is required to manage this setting."
        : "Unable to load the current pipeline. Reload to retry.");
      setLoading(false);
    });
    return () => { requestVersion.current++; };
  }, [organization.id, reload]);

  function reloadCurrent() {
    if (savingRef.current) return;
    setCurrent(null);
    setSelected("");
    setLoading(true);
    setReloadRequired(false);
    setError("");
    setMessage("");
    setReload((value) => value + 1);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!current || !selected || loading || reloadRequired || savingRef.current || selected === current.pipeline) return;
    const version = requestVersion.current;
    savingRef.current = true;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const saved = await adminService.updateOrganizationKnowledgePipeline(organization.id, selected, {
        pipeline: current.pipeline, revision: current.revision,
      });
      if (requestVersion.current !== version) return;
      setCurrent(saved);
      setSelected(saved.pipeline);
      setMessage(`Pipeline saved: ${labels[saved.pipeline]}. New requests will use this pipeline.`);
    } catch (err: unknown) {
      if (requestVersion.current !== version) return;
      setReloadRequired(true);
      setError(err instanceof ApiServiceError && err.status === 409
        ? "This setting changed elsewhere. Reload the current pipeline before saving."
        : err instanceof ApiServiceError && err.status === 403
          ? "Platform administrator access is required to manage this setting."
          : "Unable to confirm the save. Reload the current pipeline before trying again.");
    } finally {
      savingRef.current = false;
      if (requestVersion.current === version) setSaving(false);
    }
  }

  return <Card role="region" aria-labelledby="organization-pipeline-title" className="min-w-0">
    <CardHeader>
      <CardTitle id="organization-pipeline-title">Knowledge pipeline</CardTitle>
      <CardDescription className="break-words">{organization.name} · Organization #{organization.id} · {organization.bot_count} {organization.bot_count === 1 ? "bot" : "bots"}</CardDescription>
    </CardHeader>
    <CardContent className="space-y-4">
      <p id="organization-pipeline-scope" className="text-sm text-muted-foreground">Applies to all bots in this organization. New requests use the chosen pipeline. Requests already queued or running finish with their accepted pipeline.</p>
      {loading && <p role="status" className="text-sm">Loading current pipeline…</p>}
      {current && <p className="text-sm">Current pipeline: <strong>{labels[current.pipeline]}</strong></p>}
      {error && <p role="alert" className="rounded-lg border border-red-300 p-3 text-sm text-red-700 dark:text-red-300">{error}</p>}
      {message && <p role="status" className="rounded-lg bg-muted p-3 text-sm">{message}</p>}
      <form onSubmit={save} className="space-y-4">
        <label className="block space-y-2 text-sm">
          <span>Pipeline for this organization</span>
          <select aria-describedby="organization-pipeline-scope organization-pipeline-default" className="h-10 w-full min-w-0 rounded-lg border border-input bg-background px-3 text-sm sm:max-w-sm" value={selected} disabled={loading || saving || !current || reloadRequired} onChange={(event) => { setSelected(event.target.value as KnowledgePipeline); setMessage(""); }}>
            {!selected && <option value="">Select a pipeline</option>}
            <option value="rag2_improved">RAG2 Improved</option>
            <option value="og">OG</option>
          </select>
        </label>
        <p id="organization-pipeline-default" className="text-sm text-muted-foreground">RAG2 Improved is the default for new organizations. Provider usage limits still apply, including free-tier limits.</p>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={loading || saving || !current || !selected || selected === current.pipeline || reloadRequired}>{saving ? "Saving…" : "Save pipeline"}</Button>
          <Button type="button" variant="outline" disabled={loading || saving} onClick={reloadCurrent}>Reload current pipeline</Button>
          <Button type="button" variant="ghost" disabled={saving} onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </CardContent>
  </Card>;
}
