export const supportedKnowledgeExtensions = [".pdf", ".txt", ".docx"] as const;
export const supportedKnowledgeFormatsLabel = "PDF, TXT, and DOCX";
export const maxKnowledgeUploadBytes = 20 * 1024 * 1024;
export const knowledgeFileAccept = [
  ...supportedKnowledgeExtensions,
  "application/pdf",
  "text/plain",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
].join(",");

export function validateKnowledgeFile(file: Pick<File, "name" | "size">): string | null {
  const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
  if (!supportedKnowledgeExtensions.includes(extension as (typeof supportedKnowledgeExtensions)[number])) {
    return `Supported files are ${supportedKnowledgeFormatsLabel}.`;
  }
  if (file.size > maxKnowledgeUploadBytes) {
    return "File must be 20 MB or smaller.";
  }
  return null;
}
