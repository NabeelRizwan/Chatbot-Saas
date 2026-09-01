export type SharedTranscript = {
  session: { title: string; bot_name: string; created_at: string };
  messages: Array<{
    id: number;
    user_message: string;
    assistant_response: string;
    created_at: string;
  }>;
};

export function buildSharedTranscriptUrl(apiBaseUrl: string, token: string): string {
  const normalizedToken = token.trim();
  if (!normalizedToken) throw new Error("This shared conversation link is invalid.");
  return `${apiBaseUrl.replace(/\/+$/, "")}/public/share/${encodeURIComponent(normalizedToken)}`;
}

export async function fetchSharedTranscript(
  apiBaseUrl: string,
  token: string,
  fetcher: typeof fetch = fetch,
): Promise<SharedTranscript> {
  const response = await fetcher(buildSharedTranscriptUrl(apiBaseUrl, token));
  if (!response.ok) {
    throw new Error("Transcript not found or sharing has been disabled by the owner.");
  }
  return response.json() as Promise<SharedTranscript>;
}
