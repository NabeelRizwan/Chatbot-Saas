export type ChatSource = { source_url?: string; title?: string; filename?: string; citation_index?: number; cta_links?: Array<{ url: string; label?: string }> };
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
  if (!value) return null;
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; }
}

export function verifiedLinks(sources: ChatSource[] = []): Set<string> {
  return new Set(sources.flatMap((source) => [source.source_url, ...(source.cta_links || []).map((cta) => cta.url)]).map(safeLink).filter((url): url is string => Boolean(url)));
}

export function displayAnswer(message: ExperienceMessage): string {
  const references = new Map((message.sources || []).map((source) => [Number(source.citation_index), safeLink(source.source_url)]));
  return message.content.replace(/\[ID:\s*(\d+)\s*\]/g, (marker, number: string) => {
    const url = references.get(Number(number));
    return url ? `[${number}](${url.replace(/\(/g, "%28").replace(/\)/g, "%29")})` : marker;
  });
}
