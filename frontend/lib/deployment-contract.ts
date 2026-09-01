function withoutTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

export function resolveWidgetBaseUrl(configuredAppUrl: string | undefined, runtimeOrigin: string): string {
  return withoutTrailingSlash(configuredAppUrl?.trim() || runtimeOrigin);
}

export function buildPublicChatApiUrl(apiBaseUrl: string, botId: string): string {
  return `${withoutTrailingSlash(apiBaseUrl)}/public/chat/${encodeURIComponent(botId)}`;
}

export function buildWidgetScriptSnippet(widgetBaseUrl: string, apiBaseUrl: string, botId: string): string {
  return `<script
  src="${withoutTrailingSlash(widgetBaseUrl)}/widget.js"
  data-api-base-url="${withoutTrailingSlash(apiBaseUrl)}"
  data-bot-id="${botId}"
></script>`;
}

export function buildReactWidgetSnippet(widgetBaseUrl: string, apiBaseUrl: string, botId: string): string {
  return `import { useEffect } from 'react';

export default function ChatWidget() {
  useEffect(() => {
    const script = document.createElement('script');
    script.src = '${withoutTrailingSlash(widgetBaseUrl)}/widget.js';
    script.setAttribute('data-api-base-url', '${withoutTrailingSlash(apiBaseUrl)}');
    script.setAttribute('data-bot-id', '${botId}');
    script.async = true;
    document.body.appendChild(script);
  }, []);

  return null;
}`;
}

export function buildPublicChatCurl(apiBaseUrl: string, botId: string): string {
  return `curl -X POST ${buildPublicChatApiUrl(apiBaseUrl, botId)} \\
  -H "Content-Type: application/json" \\
  -d '{"message":"Hello assistant!"}'`;
}
