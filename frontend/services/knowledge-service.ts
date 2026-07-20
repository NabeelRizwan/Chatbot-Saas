import { api, request } from "@/services/api";
import type {
  BackendKnowledgeDocument,
  KnowledgeAcceptedResponse,
  KnowledgeDocument,
  KnowledgeDocumentListResponse,
} from "@/types/knowledge";

function normalizeDocument(document: BackendKnowledgeDocument): KnowledgeDocument {
  return {
    id: String(document.id),
    botId: String(document.bot_id),
    filename: document.filename,
    sourceType: document.source_type,
    sourceUrl: document.source_url,
    fileSize: document.file_size,
    processingStatus: document.processing_status,
    processingError: document.processing_error,
    chunkCount: document.chunk_count ?? 0,
    tokenCount: document.token_count ?? 0,
    metadata: document.metadata ?? {},
    createdAt: document.created_at,
    updatedAt: document.updated_at,
  };
}

export async function getDocuments(botId: string): Promise<KnowledgeDocument[]> {
  const response = await request<KnowledgeDocumentListResponse>({
    method: "GET",
    url: "/knowledge/documents",
    params: { bot_id: botId },
  });

  return response.documents.map(normalizeDocument);
}

export async function uploadFile(
  botId: string,
  file: File,
  onProgress?: (progress: number) => void,
): Promise<KnowledgeDocument> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await api.post<KnowledgeAcceptedResponse>("/knowledge/upload", formData, {
    params: { bot_id: botId },
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
    onUploadProgress: (event) => {
      if (!event.total || !onProgress) {
        return;
      }
      onProgress(Math.round((event.loaded / event.total) * 100));
    },
  });

  return normalizeDocument(response.data.document);
}

export async function crawlWebsite(botId: string, url: string): Promise<KnowledgeDocument> {
  const response = await request<KnowledgeAcceptedResponse>({
    method: "POST",
    url: "/knowledge/crawl",
    data: {
      bot_id: Number(botId),
      url,
    },
  });

  return normalizeDocument(response.document);
}

export async function deleteDocument(documentId: string): Promise<void> {
  await request<void>({
    method: "DELETE",
    url: `/knowledge/documents/${documentId}`,
  });
}

export async function reindexDocument(documentId: string): Promise<KnowledgeDocument> {
  const response = await request<KnowledgeAcceptedResponse>({
    method: "POST",
    url: `/knowledge/documents/${documentId}/reindex`,
  });

  return normalizeDocument(response.document);
}
