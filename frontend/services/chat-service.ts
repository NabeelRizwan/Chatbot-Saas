import { API_BASE_URL, request } from "@/services/api";
import type {
  BackendChatResponse,
  BackendChatSource,
  BackendRetrievedChunk,
  ChatResponse,
  ChatSource,
  RetrievedChunk,
} from "@/types/chat";

// Only an explicitly unsupported streaming route permits the legacy fallback.
// A dropped or rejected accepted stream must never silently send a second turn.
export class ChatStreamUnsupportedError extends Error {}
export type ChatStreamStatus = "queued" | "running";

function normalizeSource(source: BackendChatSource) {
  if (typeof source === "string") {
    return {
      filename: source,
      chunkRefs: [],
      ctaLinks: [],
    };
  }

  return {
    documentId: String(source.document_id),
    filename: source.filename,
    sourceUrl: source.source_url,
    chunkRefs: source.chunk_refs ?? [],
    ctaLinks: (source.cta_links ?? []).map((link) => ({
      label: link.label || link.text || "View",
      url: link.url,
    })),
  };
}

function normalizeRetrievedChunk(chunk: BackendRetrievedChunk): RetrievedChunk {
  return {
    chunkId: String(chunk.chunk_id),
    documentId: String(chunk.document_id),
    chunkIndex: chunk.chunk_index,
    content: chunk.content,
    tokenCount: chunk.token_count,
    score: chunk.score,
    sourceFilename: chunk.source_filename,
    sourceUrl: chunk.source_url,
    metadata: chunk.metadata ?? {},
  };
}

export async function sendChatMessage({
  apiKey,
  botId,
  message,
  topK = 4,
  history = [],
  accessToken,
  signal,
}: {
  apiKey?: string;
  botId: string;
  message: string;
  topK?: number;
  history?: { role: "user" | "assistant"; content: string }[];
  accessToken?: string;
  signal?: AbortSignal;
}): Promise<ChatResponse> {
  const headers: Record<string, string> = {};
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }

  const response = await request<BackendChatResponse>({
    method: "POST",
    url: accessToken ? `/chat/${botId}` : "/chat/",
    headers,
    signal,
    data: accessToken ? {
      message,
      top_k: topK,
      history,
    } : {
      api_key: apiKey,
      bot_id: Number(botId),
      message,
      top_k: topK,
      history,
    },
  });

  return {
    reply: response.reply,
    answer: response.answer,
    sources: response.sources.map(normalizeSource),
    retrievedChunks: (response.retrieved_chunks ?? []).map(normalizeRetrievedChunk),
  };
}

export async function streamChatMessage({
  apiKey,
  botId,
  message,
  history = [],
  onToken,
  onStatus,
  signal,
  accessToken,
}: {
  apiKey?: string;
  botId: string;
  message: string;
  history?: { role: "user" | "assistant"; content: string }[];
  onToken: (token: string) => void;
  onStatus?: (status: ChatStreamStatus) => void;
  signal?: AbortSignal;
  accessToken?: string;
}): Promise<{ sources: ChatSource[]; retrievedChunks: RetrievedChunk[] }> {
  const url = accessToken ? `${API_BASE_URL}/chat/${botId}/stream` : `${API_BASE_URL}/chat/stream`;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }

  const body = accessToken ? {
    message,
    top_k: 4,
    history,
  } : {
    api_key: apiKey,
    bot_id: Number(botId),
    message,
    top_k: 4,
    history,
  };

  const response = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });

  if (response.status === 404 || response.status === 405) {
    throw new ChatStreamUnsupportedError("Streaming chat is not supported by this server.");
  }
  if (!response.ok || !response.body) {
    throw new Error("Streaming chat request failed.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sources: ChatSource[] = [];
  let retrievedChunks: RetrievedChunk[] = [];
  let completed = false;

  function frame(event: string) {
      const lines = event.split("\n");
      const eventType = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
      const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
      const payload = safeParseJson(data);
      if (eventType === "error" || payload.type === "error") {
        throw new Error(typeof payload.detail === "string" ? payload.detail : typeof payload.message === "string" ? payload.message : "Streaming chat request failed.");
      }
      if (!data) return; // SSE keepalives do not become visible answer text.
      if (payload.type === "queued" || (payload.type === "meta" && payload.queued === true)) onStatus?.("queued");
      else if (payload.type === "status" || (payload.type === "meta" && payload.buffered === true)) onStatus?.("running");
      if (typeof payload.token === "string") {
        onToken(payload.token);
      }
      if (Array.isArray(payload.sources)) {
        sources = (payload.sources as BackendChatSource[]).map(normalizeSource);
      }
      if (Array.isArray(payload.retrieved_chunks)) {
        retrievedChunks = (payload.retrieved_chunks as BackendRetrievedChunk[]).map(normalizeRetrievedChunk);
      }
      if (payload.done === true || payload.type === "done" || eventType === "done") completed = true;
  }

  try {
    // Native fetch has no client deadline; the server owns pipeline-specific
    // deadlines. Keepalive bytes may continue while a grounded reply is prepared.
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        frame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
      }
      if (done) {
        if (buffer.trim()) frame(buffer);
        break;
      }
    }
    if (!completed) throw new Error("The reply was interrupted before completion.");
  } finally {
    if (!completed) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }

  return { sources, retrievedChunks };
}

function safeParseJson(value: string): Record<string, unknown> {
  try {
    return JSON.parse(value);
  } catch {
    return {};
  }
}
