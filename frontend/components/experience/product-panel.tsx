"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { ExternalLink, Pencil, Plus, Save, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { experienceService } from "@/services/experience";
import type { ExperienceProduct } from "@/types/experience";
import { EmptyState, Field, inputClass, LoadError, LoadingState, messageOf, Notice, SourcePicker, Toggle, useCollection } from "./shared";

type ProductFields = { title: string; description: string; url: string; image_url: string; price_amount: string; currency: string; enabled: boolean };
const defaults: ProductFields = { title: "", description: "", url: "", image_url: "", price_amount: "", currency: "USD", enabled: true };

export function ProductPanel({ botId, canEdit }: { botId: string; canEdit: boolean }) {
  const { items, loading, error, load } = useCollection(botId, experienceService.products);
  const [editing, setEditing] = useState<number | undefined>();
  const [source, setSource] = useState<number | null>(null);
  const [formError, setFormError] = useState("");
  const [deleting, setDeleting] = useState<number | null>(null);
  const form = useForm<ProductFields>({ defaultValues: defaults });
  function reset() { setEditing(undefined); setSource(null); setFormError(""); form.reset(defaults); }
  function edit(item: ExperienceProduct) { setEditing(item.id); setSource(item.source_document_id); setFormError(""); form.reset({ ...item, image_url: item.image_url ?? "", price_amount: item.price_amount ?? "" }); document.getElementById("product-editor")?.scrollIntoView({ behavior: "smooth", block: "start" }); setTimeout(() => form.setFocus("title"), 50); }
  async function save(values: ProductFields) {
    setFormError("");
    try { await experienceService.saveProduct(botId, { ...values, title: values.title.trim(), description: values.description.trim(), url: values.url.trim(), image_url: values.image_url.trim() || null, price_amount: values.price_amount || null, currency: values.currency.toUpperCase(), source_document_id: source }, editing); reset(); await load(); }
    catch (reason) { setFormError(messageOf(reason)); }
  }
  async function remove(item: ExperienceProduct) { if (!window.confirm(`Delete the card “${item.title}”?`)) return; setDeleting(item.id); try { await experienceService.deleteProduct(botId, item.id); if (editing === item.id) reset(); await load(); } catch (reason) { setFormError(messageOf(reason)); } finally { setDeleting(null); } }

  return <div className="grid items-start gap-6 xl:grid-cols-2">
    <Card><CardHeader><CardTitle>Product & service cards</CardTitle><CardDescription>Give visitors a useful next step when an answer uses the matching source.</CardDescription></CardHeader><CardContent className="space-y-4">
      <Notice>Cards appear for matching answer sources, not for every retrieved page. Prices are optional and manually maintained. The button opens your real product or service page; it does not place an order.</Notice>
      {loading ? <LoadingState /> : error ? <LoadError error={error} retry={() => void load()} /> : !items.length ? <EmptyState>No cards yet. Add a product or service and link its knowledge source.</EmptyState> : <div className="space-y-3">{items.map((item) => <article key={item.id} className="rounded-xl border border-border p-4"><div className="flex items-start justify-between gap-2"><h3 className="font-medium break-words">{item.title}</h3><span className="rounded-full bg-muted px-2 py-1 text-xs text-muted-foreground">{item.enabled ? "Enabled" : "Disabled"}</span></div><p className="mt-2 line-clamp-3 whitespace-pre-wrap text-sm text-muted-foreground">{item.description}</p>{(item.source_status === "changed" || item.source_status === "missing") && <div className="mt-3"><Notice>Source {item.source_status}. This card is paused. Review its details and source, then save it again.</Notice></div>}{item.price_amount !== null && <p className="mt-2 text-sm font-semibold">{item.currency} {item.price_amount}</p>}<a href={item.url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline">Open destination<ExternalLink className="h-3.5 w-3.5" /></a>{canEdit && <div className="mt-3 flex gap-2"><Button size="sm" variant="outline" onClick={() => edit(item)}><Pencil className="h-3.5 w-3.5" />Edit</Button><Button size="sm" variant="ghost" disabled={deleting !== null} onClick={() => void remove(item)}><Trash2 className="h-3.5 w-3.5" />Delete</Button></div>}</article>)}</div>}
    </CardContent></Card>
    {canEdit && <Card id="product-editor" className="scroll-mt-6"><CardHeader><div className="flex justify-between gap-2"><CardTitle>{editing ? "Edit card" : "Add a card"}</CardTitle>{editing && <Button size="sm" variant="ghost" onClick={reset}><Plus className="h-4 w-4" />New</Button>}</div></CardHeader><CardContent><form onSubmit={form.handleSubmit(save)} className="space-y-4"><fieldset disabled={form.formState.isSubmitting} className="space-y-4">
      <Field label="Product or service name"><input required maxLength={200} className={inputClass} {...form.register("title", { required: true })} /></Field>
      <Field label="Short description"><textarea rows={3} maxLength={1000} className={inputClass} {...form.register("description")} /></Field>
      <Field label="Destination page"><input required type="url" className={inputClass} placeholder="https://example.com/products/your-product" {...form.register("url", { required: true })} /></Field>
      <Field label="Image link (optional)"><input type="url" className={inputClass} placeholder="https://example.com/product.jpg" {...form.register("image_url")} /></Field>
      <div className="grid grid-cols-2 gap-3"><Field label="Price (optional)"><input type="number" min="0" step="0.01" className={inputClass} {...form.register("price_amount")} /></Field><Field label="Currency"><input required minLength={3} maxLength={3} pattern="[A-Za-z]{3}" className={`${inputClass} uppercase`} {...form.register("currency", { required: true })} /></Field></div>
      <SourcePicker botId={botId} value={source} onChange={setSource} />
      <Toggle label="Enabled" description="Also turn on product cards in Experience settings." checked={form.watch("enabled")} onChange={(value) => form.setValue("enabled", value, { shouldDirty: true })} />
    </fieldset>{formError && <Notice error>{formError}</Notice>}<div className="flex gap-2"><Button type="submit" disabled={form.formState.isSubmitting}><Save className="h-4 w-4" />{form.formState.isSubmitting ? "Saving…" : "Save card"}</Button>{editing && <Button variant="outline" type="button" onClick={reset}>Cancel edit</Button>}</div></form></CardContent></Card>}
  </div>;
}
