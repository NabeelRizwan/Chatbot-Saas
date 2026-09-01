export type PrintableTranscriptMessage = {
  userMessage?: string | null;
  assistantResponse?: string | null;
  createdAt: string;
};

export type PrintableTranscript = {
  title: string;
  botName: string;
  sessionId: string;
  createdAt: string;
  messages: PrintableTranscriptMessage[];
};

export function escapeTranscriptHtml(value: string | null | undefined): string {
  return String(value ?? "").replace(/[&<>"']/g, (character) => {
    const escaped: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return escaped[character];
  });
}

export function buildPrintableTranscriptHtml(transcript: PrintableTranscript): string {
  const title = escapeTranscriptHtml(transcript.title);
  const botName = escapeTranscriptHtml(transcript.botName);
  const sessionId = escapeTranscriptHtml(transcript.sessionId);
  const createdAt = escapeTranscriptHtml(transcript.createdAt);

  const messages = transcript.messages
    .map((message) => {
      const timestamp = escapeTranscriptHtml(message.createdAt);
      const userBlock = message.userMessage
        ? `
          <div class="message">
            <div class="message-header"><span class="user">User</span><span class="timestamp">${timestamp}</span></div>
            <div class="content">${escapeTranscriptHtml(message.userMessage)}</div>
          </div>`
        : "";
      const assistantResponse = escapeTranscriptHtml(message.assistantResponse || "[No response]");

      return `${userBlock}
        <div class="message">
          <div class="message-header"><span class="bot">${botName}</span><span class="timestamp">${timestamp}</span></div>
          <div class="content">${assistantResponse}</div>
        </div>`;
    })
    .join("");

  return `<!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <title>Transcript - ${title}</title>
        <style>
          body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 40px; color: #1e293b; max-width: 800px; margin: 0 auto; line-height: 1.6; }
          h1 { font-size: 24px; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; margin-bottom: 5px; }
          .meta { color: #64748b; font-size: 13px; margin-bottom: 40px; }
          .message { margin-bottom: 25px; }
          .message-header { display: flex; justify-content: space-between; gap: 16px; }
          .user { font-weight: bold; color: #2563eb; }
          .bot { font-weight: bold; color: #0f172a; }
          .timestamp { color: #64748b; font-size: 12px; }
          .content { margin-top: 5px; padding-left: 15px; border-left: 3px solid #e2e8f0; white-space: pre-wrap; font-size: 14px; }
        </style>
      </head>
      <body>
        <h1>Transcript: ${title}</h1>
        <div class="meta">
          <strong>Bot:</strong> ${botName} |
          <strong>Created:</strong> ${createdAt} |
          <strong>Session ID:</strong> ${sessionId}
        </div>
        ${messages}
      </body>
    </html>`;
}
