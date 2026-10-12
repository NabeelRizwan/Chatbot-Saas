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
  const quote = (value: string) => `'${value.replace(/'/g, "'\\''")}'`;
  const sessionUrl = `${withoutTrailingSlash(apiBaseUrl)}/public/widget/${encodeURIComponent(botId)}/session`;
  return `# Requires Bash, curl and Python 3.
# Set a website origin listed in this bot's Allowed embed origins.
# The bot must be Active. Keep session tokens private.
origin='https://your-website.example'

# 1. Create an authenticated visitor session.
session=$(curl --fail-with-body --silent --show-error -X POST ${quote(sessionUrl)} \\
  -H "Origin: $origin") || exit 1

# 2. Send a question using that session and a unique delivery ID.
payload=$(printf '%s' "$session" | python3 -c 'import json,sys,uuid; s=json.load(sys.stdin); print(json.dumps({"session_id":s["session_id"],"session_token":s["session_token"],"turn_id":str(uuid.uuid4()),"message":"Hello assistant!"}))') || exit 1
curl --fail-with-body --silent --show-error -X POST ${quote(buildPublicChatApiUrl(apiBaseUrl, botId))} \\
  -H "Origin: $origin" \\
  -H "Content-Type: application/json" \\
  --data "$payload"`;
}
