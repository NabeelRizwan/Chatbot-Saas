import { API_BASE_URL, request } from "@/services/api";
import type {
  BackendChatResponse,
  BackendChatSource,
  BackendRetrievedChunk,
  ChatResponse,
  ChatSource,
  RetrievedChunk,
} from "@/types/chat";

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
}: {
  apiKey?: string;
  botId: string;
  message: string;
  topK?: number;
  history?: { role: "user" | "assistant"; content: string }[];
  accessToken?: string;
}): Promise<ChatResponse> {
  const headers: Record<string, string> = {};
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }

  const response = await request<BackendChatResponse>({
    method: "POST",
    url: accessToken ? `/chat/${botId}` : "/chat/",
    headers,
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
  signal,
  accessToken,
}: {
  apiKey?: string;
  botId: string;
  message: string;
  history?: { role: "user" | "assistant"; content: string }[];
  onToken: (token: string) => void;
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

  if (!response.ok || !response.body) {
    throw new Error("Streaming chat request failed.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sources: ChatSource[] = [];
  let retrievedChunks: RetrievedChunk[] = [];

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const event of events) {
      const dataLine = event.split("\n").find((line) => line.startsWith("data: "));
      if (event.startsWith("event: error")) {
        const errorPayload = dataLine ? safeParseJson(dataLine.slice(6)) : {};
        throw new Error(typeof errorPayload.detail === "string" ? errorPayload.detail : "Streaming chat request failed.");
      }
      if (!dataLine) {
        continue;
      }
      const payload = safeParseJson(dataLine.slice(6));
      if (typeof payload.token === "string") {
        onToken(payload.token);
      }
      if (Array.isArray(payload.sources)) {
        sources = (payload.sources as BackendChatSource[]).map(normalizeSource);
      }
      if (Array.isArray(payload.retrieved_chunks)) {
        retrievedChunks = (payload.retrieved_chunks as BackendRetrievedChunk[]).map(normalizeRetrievedChunk);
      }
    }
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
