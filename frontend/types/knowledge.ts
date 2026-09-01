export type ProcessingStatus = "pending" | "processing" | "completed" | "failed";
export type KnowledgeSourceType = "pdf" | "txt" | "docx" | "website" | "text";
export type KnowledgeLifecycleStatus = "active" | "ready" | "processing" | "failed" | "superseded" | string;
export type KnowledgeJobStatus = "queued" | "crawling" | "processing" | "embedding" | "validating" | "ready" | "failed" | "cancelling" | "cancelled" | "retrying";
export type CrawlMode = "recursive" | "single_page";

export type CrawlUrlResult = { url: string; result: "skipped" | "failed"; reason: string };
export type CrawlCoverage = {
  discovered: number; eligible: number; crawled: number; indexed: number; skipped: number; failed: number;
  duplicates: number; maximumDepth: number; coveragePercent?: number | null; documents: number; chunks: number;
  urlResults: CrawlUrlResult[];
};
export type KnowledgeJob = {
  jobId: string; botId: string; sourceName: string; sourceUrl?: string | null;
  ingestionType: "upload" | "website"; status: KnowledgeJobStatus; stage: string;
  progressPercent?: number | null; attemptNumber: number; retryable: boolean; cancellable: boolean;
  createdAt: string; startedAt?: string | null; completedAt?: string | null;
  errorCode?: string | null; errorMessage?: string | null; crawlCoverage?: CrawlCoverage | null;
  activeVersion?: number | null; candidateVersion?: number | null; versionState?: string | null; chunksCreated: number;
};
export type KnowledgeDocument = {
  id: string; botId: string; filename: string; sourceType: KnowledgeSourceType | string; sourceUrl?: string | null;
  fileSize?: number | null; logicalSizeBytes: number; processingStatus: ProcessingStatus; processingError?: string | null;
  lifecycleStatus: KnowledgeLifecycleStatus; active: boolean; version: number; pageCount: number; lastIndexedAt?: string | null;
  chunkCount: number; tokenCount: number; metadata: Record<string, unknown>; createdAt: string; updatedAt: string;
};
export type BackendKnowledgeDocument = {
  id: number | string; bot_id: number | string; filename: string; source_type: string; source_url?: string | null;
  file_size?: number | null; logical_size_bytes: number; processing_status: ProcessingStatus; processing_error?: string | null;
  lifecycle_status?: string; active?: boolean; version?: number; page_count?: number; last_indexed_at?: string | null;
  chunk_count: number; token_count: number; metadata?: Record<string, unknown>; created_at: string; updated_at: string;
};
export type BackendKnowledgeJob = {
  job_id: string; bot_id: number | string; source_name: string; source_url?: string | null;
  ingestion_type: "upload" | "website"; status: KnowledgeJobStatus; stage: string; progress_percent?: number | null;
  attempt_number: number; retryable: boolean; cancellable: boolean; created_at: string; started_at?: string | null;
  completed_at?: string | null; error_code?: string | null; error_message?: string | null;
  crawl_coverage?: { discovered: number; eligible: number; crawled: number; indexed: number; skipped: number; failed: number;
    duplicates: number; maximum_depth: number; coverage_percent?: number | null; documents: number; chunks: number;
    url_results?: CrawlUrlResult[] } | null;
  active_version?: number | null; candidate_version?: number | null; version_state?: string | null; chunks_created: number;
};
export type KnowledgeAcceptedResponse = { document: BackendKnowledgeDocument; message: string; job_id: string };
export type KnowledgeDocumentListResponse = { documents: BackendKnowledgeDocument[] };
export type KnowledgeJobListResponse = { jobs: BackendKnowledgeJob[] };
