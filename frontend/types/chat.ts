export type RetrievedChunk = {
  chunkId: string;
  documentId: string;
  chunkIndex: number;
  content: string;
  tokenCount: number;
  score?: number | null;
  sourceFilename: string;
  sourceUrl?: string | null;
  metadata: Record<string, unknown>;
};

export type ChatSource = {
  documentId?: string;
  filename: string;
  sourceUrl?: string | null;
  chunkRefs: number[];
};

export type BackendRetrievedChunk = {
  chunk_id: number | string;
  document_id: number | string;
  chunk_index: number;
  content: string;
  token_count: number;
  score?: number | null;
  source_filename: string;
  source_url?: string | null;
  metadata?: Record<string, unknown>;
};

export type BackendChatSource =
  | string
  | {
      document_id: number | string;
      filename: string;
      source_url?: string | null;
      chunk_refs: number[];
    };

export type ChatResponse = {
  reply: string;
  answer?: string | null;
  sources: ChatSource[];
  retrievedChunks: RetrievedChunk[];
};

export type BackendChatResponse = {
  reply: string;
  answer?: string | null;
  sources: BackendChatSource[];
  retrieved_chunks?: BackendRetrievedChunk[];
};
