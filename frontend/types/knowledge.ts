export type ProcessingStatus = "pending" | "processing" | "completed" | "failed";
export type KnowledgeSourceType = "pdf" | "txt" | "docx" | "website" | "text";

export type KnowledgeDocument = {
  id: string;
  botId: string;
  filename: string;
  sourceType: KnowledgeSourceType | string;
  sourceUrl?: string | null;
  fileSize?: number | null;
  processingStatus: ProcessingStatus;
  processingError?: string | null;
  chunkCount: number;
  tokenCount: number;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type BackendKnowledgeDocument = {
  id: number | string;
  bot_id: number | string;
  filename: string;
  source_type: string;
  source_url?: string | null;
  file_size?: number | null;
  processing_status: ProcessingStatus;
  processing_error?: string | null;
  chunk_count: number;
  token_count: number;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type KnowledgeAcceptedResponse = {
  document: BackendKnowledgeDocument;
  message: string;
};

export type KnowledgeDocumentListResponse = {
  documents: BackendKnowledgeDocument[];
};
