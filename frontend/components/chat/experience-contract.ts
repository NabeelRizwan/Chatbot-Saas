export type ChatSource = { source_url?: string | null; title?: string; filename?: string; citation_index?: number; attribution_scope?: "selected"; cta_links?: Array<{ url: string; label?: string }> };
export type SourceLink = { label: string; url: string | null };
export type ProductCard = { id: string; title: string; description?: string; url: string; image_url?: string | null; price_amount?: string | null; currency?: string | null };
export type ExperienceMessage = {
  id: string; role: "user" | "assistant"; content: string; created_at?: string;
  turn_id?: string; status?: string; sources?: ChatSource[]; products?: ProductCard[]; needs_ack?: boolean;
};
export type ExperienceSettings = {
  enabled?: boolean; suggested_questions?: string[]; hosted_chat_enabled?: boolean;
  lead_form_enabled?: boolean; lead_consent_text?: string; product_cards_enabled?: boolean;
  theme?: "light" | "dark" | "auto"; font_family?: "system" | "inter" | "serif";
  density?: "comfortable" | "compact"; corner_style?: "rounded" | "soft" | "square";
};
export type ExperienceSnapshot = {
  messages: ExperienceMessage[]; running: boolean; ready: boolean; native: boolean;
  error: string; canRetry: boolean; open: boolean; standalone: boolean;
  config: { botName: string; welcomeMessage: string; primaryColor: string; accentColor: string; placeholderText: string; botAvatarUrl?: string };
  experience: ExperienceSettings;
  actions?: Array<{ label: string; url: string; kind: string }>;
  lead?: { status: "idle" | "sending" | "saved" | "error"; message?: string };
};
export type BridgeCommand = { action: string; [key: string]: unknown };

export function safeLink(value: string | undefined | null): string | null {
  // eslint-disable-next-line no-control-regex -- Reject control characters before URL parsing can silently remove them.
  if (typeof value !== "string" || !/^https?:\/\/[^/?#]+/i.test(value) || value.length > 2048 || /\s|[\u0000-\u001f\u007f-\u009f\\]/.test(value) || /^[a-z][a-z0-9+.-]*:\/\/[^/?#]*@/i.test(value)) return null;
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; }
}

// Source identities and URLs come from the backend sidecar, never the answer.
// Multiple cited passages can share a page; keep one visible link per URL.
export function sourceLinks(sources: ChatSource[] = []): SourceLink[] {
  const entries: SourceLink[] = [];
  const seen = new Set<string>();
  for (const source of Array.isArray(sources) ? sources : []) {
    if (!source || typeof source !== "object") continue;
    const label = typeof source.title === "string" && source.title || typeof source.filename === "string" && source.filename || "Source";
    const url = safeLink(source.source_url);
    const ctas = Array.isArray(source.cta_links) ? source.cta_links.filter((cta) => cta && typeof cta === "object") : [];
    const links = [{ label, url }, ...ctas.map((cta) => ({ label: typeof cta.label === "string" && cta.label || "View", url: safeLink(cta.url) }))].filter((link) => link.url);
    if (!links.length) {
      const key = "label:" + label;
      if (!seen.has(key)) { seen.add(key); entries.push({ label, url: null }); }
    }
    for (const link of links) {
      if (!seen.has(link.url!)) { seen.add(link.url!); entries.push(link); }
    }
  }
  return entries;
}

export function verifiedLinks(sources: ChatSource[] = []): Set<string> {
  return new Set(sourceLinks(sources).map((source) => source.url).filter((url): url is string => Boolean(url)));
}

export function citationUrlMap(sources: ChatSource[] = []): Map<number, string> {
  const references = new Map<number, string | null>();
  const ambiguous = new Set<number>();
  for (const source of Array.isArray(sources) ? sources : []) {
    if (!source || typeof source !== "object") continue;
    const index = source.citation_index;
    if (typeof index !== "number" || !Number.isSafeInteger(index) || index < 1) continue;
    const url = safeLink(source.source_url);
    if (references.has(index) && references.get(index) !== url) ambiguous.add(index);
    references.set(index, url);
  }
  return new Map([...references].filter((entry): entry is [number, string] => Boolean(entry[1]) && !ambiguous.has(entry[0])));
}

export function displayAnswer(message: ExperienceMessage): string {
  const references = citationUrlMap(message.sources);
  return message.content.replace(/\[ID:\s*(\d+)\s*\]/g, (marker, number: string) => {
    const url = references.get(Number(number));
    return url ? `[${number}](${url.replace(/\(/g, "%28").replace(/\)/g, "%29")})` : marker;
  });
}
