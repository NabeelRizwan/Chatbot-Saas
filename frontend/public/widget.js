(function () {
  const currentScript = document.currentScript;
  const scriptOrigin = currentScript && currentScript.src ? new URL(currentScript.src).origin : "";
  const instances = new Map();

  const defaultConfig = {
    botName: "AI Assistant",
    welcomeMessage: "Hi, how can I help you today?",
    primaryColor: "#2563eb",
    accentColor: "#0f172a",
    launcherText: "Chat",
    launcherTitle: "Chat with us",
    launcherIcon: "message",
    botAvatarUrl: null,
    position: "bottom-right",
    placeholderText: "Ask a question...",
  };

  function normalizeConfig(payload) {
    return {
      botName: payload.bot_name || payload.botName || defaultConfig.botName,
      welcomeMessage: String(payload.welcome_message || payload.welcomeMessage || "").trim() || defaultConfig.welcomeMessage,
      primaryColor: payload.primary_color || payload.primaryColor || defaultConfig.primaryColor,
      accentColor: payload.accent_color || payload.accentColor || defaultConfig.accentColor,
      launcherText: payload.launcher_text || payload.launcherText || defaultConfig.launcherText,
      launcherTitle: payload.launcher_title || payload.launcherTitle || defaultConfig.launcherTitle,
      launcherIcon: payload.launcher_icon || payload.launcherIcon || defaultConfig.launcherIcon,
      botAvatarUrl: payload.bot_avatar_url || payload.botAvatarUrl || defaultConfig.botAvatarUrl,
      position: payload.position || defaultConfig.position,
      placeholderText: payload.placeholder_text || payload.placeholderText || defaultConfig.placeholderText,
      nativeSessionV1: payload.native_session_v1 === true,
    };
  }

  function getSessionStorage() {
    try {
      const storage = window.sessionStorage;
      const testKey = "__chatbot_widget_storage_test__";
      storage.setItem(testKey, "1");
      storage.removeItem(testKey);
      return storage;
    } catch (error) {
      return null;
    }
  }

  function createElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) {
      element.className = className;
    }
    if (text) {
      element.textContent = text;
    }
    return element;
  }

  function safeHttpUrl(value) {
    if (typeof value !== "string" || !/^https?:\/\/[^/?#]+/i.test(value) || value.length > 2048 || /\s|[\u0000-\u001f\u007f-\u009f\\]/.test(value) || /^[a-z][a-z0-9+.-]*:\/\/[^/?#]*@/i.test(value)) return null;
    try {
      const parsed = new URL(String(value));
      return (parsed.protocol === "https:" || parsed.protocol === "http:") && !parsed.username && !parsed.password ? parsed.href : null;
    } catch (error) {
      return null;
    }
  }

  function appendInlineMarkdown(parent, value, verifiedUrls) {
    const text = String(value || "");
    const tokenPattern = /(\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|_([^_]+)_|\*([^*]+)\*)/g;
    let cursor = 0;
    let match;
    while ((match = tokenPattern.exec(text))) {
      if (match.index > cursor) {
        parent.appendChild(document.createTextNode(text.slice(cursor, match.index)));
      }
      if (match[2] !== undefined) {
        const href = safeHttpUrl(match[3]);
        if (href && verifiedUrls.has(href)) {
          const link = createElement("a", "cw-link", match[2]);
          link.href = href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          parent.appendChild(link);
        } else {
          parent.appendChild(document.createTextNode(match[2]));
        }
      } else if (match[4] !== undefined) {
        const strong = createElement("strong");
        appendInlineMarkdown(strong, match[4], verifiedUrls);
        parent.appendChild(strong);
      } else {
        const emphasis = createElement("em");
        emphasis.textContent = match[5] !== undefined ? match[5] : match[6];
        parent.appendChild(emphasis);
      }
      cursor = tokenPattern.lastIndex;
    }
    if (cursor < text.length) {
      parent.appendChild(document.createTextNode(text.slice(cursor)));
    }
  }

  function renderSafeMarkdown(container, markdown, verifiedUrls) {
    container.textContent = "";
    const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
    let index = 0;
    while (index < lines.length) {
      if (!lines[index].trim()) {
        index += 1;
        continue;
      }
      if (
        lines[index].includes("|") &&
        index + 1 < lines.length &&
        /^\s*\|?[\s:|-]+\|[\s:|-]*\|?\s*$/.test(lines[index + 1])
      ) {
        const wrapper = createElement("div", "cw-table-wrap");
        const table = createElement("table", "cw-table");
        const rows = [];
        rows.push(lines[index]);
        index += 2;
        while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
          rows.push(lines[index]);
          index += 1;
        }
        rows.forEach(function (line, rowIndex) {
          const row = document.createElement("tr");
          line.replace(/^\s*\||\|\s*$/g, "").split("|").forEach(function (cellText) {
            const cell = document.createElement(rowIndex === 0 ? "th" : "td");
            appendInlineMarkdown(cell, cellText.trim(), verifiedUrls);
            row.appendChild(cell);
          });
          table.appendChild(row);
        });
        wrapper.appendChild(table);
        container.appendChild(wrapper);
        continue;
      }
      const listMatch = lines[index].match(/^\s*(?:([-*+])|(\d+)\.)\s+(.+)$/);
      if (listMatch) {
        const ordered = Boolean(listMatch[2]);
        const list = document.createElement(ordered ? "ol" : "ul");
        while (index < lines.length) {
          const itemMatch = lines[index].match(/^\s*(?:([-*+])|(\d+)\.)\s+(.+)$/);
          if (!itemMatch || Boolean(itemMatch[2]) !== ordered) break;
          const item = document.createElement("li");
          appendInlineMarkdown(item, itemMatch[3], verifiedUrls);
          list.appendChild(item);
          index += 1;
        }
        container.appendChild(list);
        continue;
      }
      const paragraphLines = [];
      while (
        index < lines.length &&
        lines[index].trim() &&
        !/^\s*(?:[-*+]|\d+\.)\s+/.test(lines[index])
      ) {
        paragraphLines.push(lines[index]);
        index += 1;
      }
      const paragraph = document.createElement("p");
      paragraphLines.forEach(function (line, lineIndex) {
        if (lineIndex) paragraph.appendChild(document.createElement("br"));
        appendInlineMarkdown(paragraph, line, verifiedUrls);
      });
      container.appendChild(paragraph);
    }
  }

  function verifiedUrlSet(sources) {
    return new Set(sourceLinks(sources).map(function (source) { return source.url; }).filter(Boolean));
  }

  function sourceLinks(sources) {
    const entries = [];
    const seen = new Set();
    (Array.isArray(sources) ? sources : []).forEach(function (source) {
      if (!source || typeof source !== "object") return;
      const label = typeof source.title === "string" && source.title || typeof source.filename === "string" && source.filename || "Source";
      const ctas = Array.isArray(source.cta_links) ? source.cta_links.filter(function (cta) { return cta && typeof cta === "object"; }) : [];
      const links = [{ label: label, url: safeHttpUrl(source.source_url) }].concat(ctas.map(function (cta) {
        return { label: typeof cta.label === "string" && cta.label || "View", url: safeHttpUrl(cta.url) };
      })).filter(function (link) { return link.url; });
      if (!links.length && !seen.has("label:" + label)) {
        seen.add("label:" + label);
        entries.push({ label: label, url: null });
      }
      links.forEach(function (link) {
        if (!seen.has(link.url)) { seen.add(link.url); entries.push(link); }
      });
    });
    return entries;
  }

  function citationDestinations(sources) {
    const references = new Map();
    const ambiguous = new Set();
    (Array.isArray(sources) ? sources : []).forEach(function (source) {
      if (!source || typeof source !== "object") return;
      const index = source.citation_index;
      if (typeof index !== "number" || !Number.isSafeInteger(index) || index < 1) return;
      const url = safeHttpUrl(source.source_url);
      if (references.has(index) && references.get(index) !== url) ambiguous.add(index);
      references.set(index, url);
    });
    return new Map(Array.from(references).filter(function (entry) { return !ambiguous.has(entry[0]); }));
  }

  function citationUrlMap(sources) {
    return new Map(Array.from(citationDestinations(sources)).filter(function (entry) { return entry[1]; }));
  }

  function presentedSources(content, sources, native) {
    if (!native) return sources || [];
    const used = new Set(Array.from(String(content).matchAll(/\[ID:\s*(\d+)\s*\]/g), function (match) { return Number(match[1]); }));
    const unambiguous = citationDestinations(sources);
    // Native legacy sources are candidates. Only an explicit backend marker
    // identifies an already selected source-map sidecar without inline IDs.
    return (Array.isArray(sources) ? sources : []).filter(function (source) {
      return source && typeof source === "object" && (source.attribution_scope === "selected" || (used.has(source.citation_index) && unambiguous.has(source.citation_index)));
    });
  }

  function iconSvg(name) {
    if (name === "bot") return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 2h2v3h4a4 4 0 0 1 4 4v9a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V9a4 4 0 0 1 4-4h4V2zm-4 5a2 2 0 0 0-2 2v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9a2 2 0 0 0-2-2H7zm1 3h2v3H8v-3zm6 0h2v3h-2v-3zm-6 6h8v2H8v-2z"/></svg>';
    if (name === "support") return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 2a8 8 0 1 1 0 16 8 8 0 0 1 0-16zm0 3a3 3 0 0 1 1 5.83V14h-2v-2.5l.75-.2A1.2 1.2 0 1 0 10.8 10H9a3 3 0 0 1 3-3zm-1 9h2v2h-2v-2z"/></svg>';
    if (name === "sparkle") {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.7 5.1L19 10l-5.3 1.9L12 17l-1.7-5.1L5 10l5.3-1.9L12 3zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15z"/></svg>';
    }
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6.5A3.5 3.5 0 0 1 8.5 3h7A3.5 3.5 0 0 1 19 6.5v5A3.5 3.5 0 0 1 15.5 15H11l-4.2 3.6A1 1 0 0 1 5.2 18v-3.2A3.5 3.5 0 0 1 2 11.5v-5z"/></svg>';
  }

  function appendStyles(root) {
    const style = document.createElement("style");
    style.textContent = `
:host { color-scheme: light; }
* { box-sizing: border-box; }
button, textarea { font: inherit; }
button, a { -webkit-tap-highlight-color: transparent; }
button { cursor: pointer; }
button:disabled { cursor: default; }
[hidden] { display: none !important; }
:focus-visible { outline: 3px solid var(--cw-primary); outline-offset: 3px; }
.cw-root { --cw-primary:#2563eb; --cw-accent:#0f172a; --cw-bottom:22px; --cw-side:24px; --cw-ink:#18342e; --cw-muted:#62736d; position:fixed; z-index:2147483000; font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--cw-ink); font-size:14px; line-height:1.5; }
.cw-bottom-right { right:var(--cw-side); bottom:var(--cw-bottom); }
.cw-bottom-left { left:var(--cw-side); bottom:var(--cw-bottom); }
.cw-launcher { display:inline-flex; align-items:center; gap:11px; height:58px; min-width:58px; padding:0 22px; border:1px solid #ffffff35; border-radius:20px; background:var(--cw-primary); color:#fff; font-size:14px; font-weight:650; box-shadow:0 8px 24px #173c3426,0 2px 5px #173c3414; transition:transform .2s,box-shadow .2s; }
.cw-launcher:hover { transform:translateY(-3px); box-shadow:0 12px 28px #173c3430; }
.cw-launcher svg { width:23px; height:23px; fill:currentColor; display:block; }
.cw-open .cw-launcher { box-shadow:0 4px 12px #173c341f; }
.cw-panel { position:absolute; bottom:74px; width:min(440px,calc(100vw - 40px)); height:min(710px,calc(100vh - 120px)); height:min(710px,calc(100dvh - 120px)); display:flex; flex-direction:column; background:#fff; border:1px solid #dce5df; border-radius:24px; overflow:hidden; box-shadow:0 24px 80px #163b3429,0 4px 16px #163b3412; opacity:0; visibility:hidden; pointer-events:none; transform:translateY(14px) scale(.98); transform-origin:bottom right; transition:opacity .2s,transform .2s,visibility .2s; }
.cw-bottom-right .cw-panel { right:0; }
.cw-bottom-left .cw-panel { left:0; transform-origin:bottom left; }
.cw-open .cw-panel { opacity:1; visibility:visible; pointer-events:auto; transform:none; }
.cw-header { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:22px 20px 18px; background:#fff; border-top:4px solid var(--cw-primary); border-bottom:1px solid #edf1ed; flex-shrink:0; }
.cw-heading { display:flex; align-items:center; gap:12px; min-width:0; flex:1; }
.cw-avatar { display:flex; align-items:center; justify-content:center; width:44px; height:44px; flex:none; border-radius:15px; background:color-mix(in srgb,var(--cw-primary) 9%,white); color:var(--cw-primary); border:1px solid color-mix(in srgb,var(--cw-primary) 12%,white); overflow:hidden; }
.cw-avatar svg { width:23px; height:23px; fill:currentColor; }
.cw-avatar img { width:100%; height:100%; object-fit:cover; }
.cw-title { min-width:0; }
.cw-title strong { display:block; font-size:16px; letter-spacing:-.025em; font-weight:700; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; }
.cw-title span { display:flex; align-items:center; gap:5px; margin-top:3px; font-size:11px; color:var(--cw-muted); }
.cw-title span::before { content:""; width:5px; height:5px; border-radius:100%; background:var(--cw-primary); }
.cw-close { display:inline-flex; align-items:center; justify-content:center; width:36px; height:36px; flex:none; border:1px solid transparent; border-radius:11px; background:transparent; color:var(--cw-muted); font-size:24px; transition:background .15s,color .15s; }
.cw-close:hover { background:#f0f4f0; color:var(--cw-ink); }
.cw-new-chat { font-size:23px; }
.cw-stop { width:auto; padding:0 10px; height:34px; font-size:12px; border-color:#dce5df; }
.cw-messages { flex:1; min-height:0; padding:24px 20px 10px; overflow:auto; overscroll-behavior:contain; scrollbar-width:thin; scrollbar-color:#cbd8d0 transparent; background:linear-gradient(160deg,#f7faf6 0%,#fff 55%); }
.cw-message { display:flex; margin:0 0 23px; }
.cw-stack { min-width:0; max-width:100%; width:100%; }
.cw-message-user { justify-content:flex-end; }
.cw-message-user .cw-stack { width:auto; max-width:88%; }
.cw-bubble { max-width:100%; padding:0; font-size:14px; line-height:1.75; white-space:pre-wrap; overflow-wrap:anywhere; }
.cw-message-user .cw-bubble { padding:11px 16px; background:var(--cw-primary); color:#fff; border-radius:17px 17px 5px 17px; line-height:1.6; box-shadow:0 3px 8px #153e3210; }
.cw-message-assistant .cw-bubble { color:var(--cw-ink); }
.cw-message-assistant .cw-bubble:empty { display:none; }
.cw-welcome { padding:22px 0 10px; }
.cw-welcome .cw-bubble { font-size:21px; line-height:1.5; font-weight:500; letter-spacing:-.035em; max-width:310px; }
.cw-welcome .cw-bubble::before { content:"HERE TO HELP"; display:block; font-size:10px; letter-spacing:.15em; font-weight:750; color:var(--cw-primary); margin-bottom:14px; }
.cw-welcome .cw-time { display:none; }
.cw-bubble p { margin:0 0 12px; }
.cw-bubble p:last-child { margin-bottom:0; }
.cw-bubble ul,.cw-bubble ol { margin:8px 0 14px; padding-left:21px; }
.cw-bubble li + li { margin-top:6px; }
.cw-bubble strong { font-weight:700; }
.cw-link { color:var(--cw-primary); text-decoration:underline; text-underline-offset:3px; }
.cw-time { margin-top:8px; font-size:10px; color:#7c8b83; }
.cw-message-user .cw-time { text-align:right; padding-right:3px; }
.cw-table-wrap { width:100%; max-width:100%; overflow:auto; margin:12px 0; border:1px solid #dfe7df; border-radius:10px; }
.cw-table { border-collapse:collapse; min-width:100%; font-size:12px; white-space:normal; }
.cw-table th,.cw-table td { padding:9px 10px; text-align:left; vertical-align:top; border-bottom:1px solid #e3eae2; }
.cw-table th { background:#eef4ed; font-weight:650; }
.cw-table tr:last-child td { border-bottom:0; }
.cw-sources { margin-top:12px; padding:12px; border:1px solid #e0e8df; border-radius:12px; background:#f6f9f4; }
.cw-sources-title { color:var(--cw-muted); font-size:10px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; margin-bottom:8px; }
.cw-source-links { display:flex; flex-wrap:wrap; gap:6px; }
.cw-source-link { display:inline-flex; align-items:center; max-width:100%; min-height:28px; padding:4px 9px; border:1px solid #d9e3d5; border-radius:7px; background:#fff; color:var(--cw-primary); font-size:11px; line-height:1.4; text-decoration:none; white-space:normal; overflow-wrap:anywhere; transition:background .15s,border-color .15s; }
.cw-source-link:hover { background:#eaf2e5; border-color:#a9bfa1; }
.cw-citation { padding:1px 5px; min-height:22px; margin:0 2px; vertical-align:baseline; font-size:10px; white-space:nowrap; }
.cw-copy { background:transparent; border:0; color:var(--cw-muted); padding:4px 0; margin-top:4px; font-size:11px; }
.cw-copy:hover { color:var(--cw-primary); text-decoration:underline; }
.cw-typing { display:inline-flex; align-items:center; gap:5px; padding:10px 0; color:var(--cw-primary); }
.cw-dot { width:5px; height:5px; border-radius:50%; background:currentColor; animation:cw-pulse 1.4s infinite; }
.cw-dot:nth-child(2) { animation-delay:.14s; }.cw-dot:nth-child(3) { animation-delay:.28s; }
.cw-turn-status { font-size:12px; color:var(--cw-muted); display:flex; align-items:center; gap:8px; padding:8px 0; }
.cw-message-assistant[data-status="running"] .cw-turn-status::before,.cw-message-assistant[data-status="accepted"] .cw-turn-status::before,.cw-message-assistant[data-status="queued"] .cw-turn-status::before { content:""; width:7px; height:7px; border-radius:50%; background:var(--cw-primary); animation:cw-pulse 1.4s infinite; }
.cw-error { flex-shrink:0; margin:0 16px 8px; padding:11px 13px; border:1px solid #ebd6b6; border-radius:11px; background:#fff8eb; color:#795422; font-size:12px; line-height:1.6; }
.cw-retry { background:#fff; color:inherit; border:1px solid #dbc39e; border-radius:6px; padding:4px 9px; margin-left:7px; font-size:11px; font-weight:650; }
.cw-form { display:flex; align-items:flex-end; gap:8px; margin:0 16px; padding:8px; border:1px solid #d8e1d6; border-radius:17px; background:#fff; transition:border-color .2s,box-shadow .2s; flex-shrink:0; }
.cw-form:focus-within { border-color:var(--cw-primary); box-shadow:0 0 0 3px color-mix(in srgb,var(--cw-primary) 9%,transparent); }
.cw-input { flex:1; min-width:0; min-height:40px; max-height:120px; resize:none; padding:10px 6px; border:0; outline:0; background:transparent; color:var(--cw-ink); font-size:14px; line-height:1.45; }
.cw-input:focus-visible { outline:0; }
.cw-input::placeholder { color:#7b8b80; }
.cw-input:disabled { opacity:.7; }
.cw-send { width:40px; height:40px; flex:none; display:flex; align-items:center; justify-content:center; border:0; border-radius:11px; background:var(--cw-primary); color:#fff; font-size:23px; transition:opacity .15s,transform .15s; }
.cw-send:hover:not(:disabled) { transform:translateY(-2px); }.cw-send:disabled { opacity:.35; }
.cw-powered { padding:11px 14px 15px; font-size:10px; color:#718078; text-align:center; background:white; flex-shrink:0; }
.cw-jump { align-self:center; margin:0 0 10px; background:#fff; border:1px solid #d8e1d6; border-radius:99px; padding:7px 13px; font-size:11px; color:var(--cw-primary); box-shadow:0 3px 10px #153e3212; }
.cw-sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
@keyframes cw-pulse { 0%,80%,100% { opacity:.4; } 40% { opacity:1; } }
@keyframes cw-enter { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:none; } }
@media(max-width:520px) { .cw-root { --cw-side:14px; --cw-bottom:14px; }.cw-launcher { height:54px; padding:0 18px; border-radius:18px; }.cw-panel { position:fixed; inset:8px 8px auto 8px; width:calc(100vw - 16px); height:calc(100vh - 16px); height:calc(100dvh - 16px); border-radius:20px; }.cw-bottom-left .cw-panel,.cw-bottom-right .cw-panel { left:8px; right:8px; }.cw-header { padding:17px 16px 14px; }.cw-messages { padding:20px 17px 8px; }.cw-open .cw-launcher { visibility:hidden; }.cw-powered { padding-bottom:max(12px,env(safe-area-inset-bottom)); }.cw-input { font-size:16px; } }
@media(prefers-reduced-motion:reduce) { *,*::before,*::after { animation:none !important; transition:none !important; scroll-behavior:auto !important; } }
@media(forced-colors:active) { .cw-panel,.cw-bubble,.cw-form,.cw-launcher,.cw-source-link { border:1px solid CanvasText; }.cw-citation { color:LinkText; } }

    `;
    root.appendChild(style);
  }

  function mount(options) {
    if (!options || !options.botId) {
      throw new Error("ChatbotWidget.init requires a botId.");
    }

    const botId = String(options.botId);
    if (instances.has(botId)) {
      return instances.get(botId);
    }

    const apiBaseUrl = (
      currentScript?.dataset?.apiBaseUrl ||
      options?.apiBaseUrl ||
      scriptOrigin ||
      window.location.origin
    ).replace(/\/$/, "");
    const storage = getSessionStorage();
    const host = document.createElement("div");
    document.body.appendChild(host);
    const shadow = host.attachShadow({ mode: "open" });
    appendStyles(shadow);

    const root = createElement("div", "cw-root cw-bottom-right");
    const panel = createElement("section", "cw-panel");
    const panelId = "cw-panel-" + Math.random().toString(36).slice(2);
    panel.id = panelId;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Chat assistant");
    panel.setAttribute("aria-hidden", "true");
    panel.inert = true;
    const launcher = createElement("button", "cw-launcher");
    launcher.type = "button";
    launcher.setAttribute("aria-controls", panelId);
    launcher.setAttribute("aria-expanded", "false");
    launcher.setAttribute("aria-label", "Open chat");
    shadow.appendChild(root);

    const header = createElement("div", "cw-header");
    const heading = createElement("div", "cw-heading");
    const avatar = createElement("div", "cw-avatar");
    avatar.innerHTML = iconSvg(defaultConfig.launcherIcon);
    const title = createElement("div", "cw-title");
    const titleName = createElement("strong", "", defaultConfig.botName);
    const titleStatus = createElement("span", "", "AI assistant");
    const closeButton = createElement("button", "cw-close", "×");
    closeButton.type = "button";
    closeButton.setAttribute("aria-label", "Close chat");
    heading.appendChild(avatar);
    title.appendChild(titleName);
    title.appendChild(titleStatus);
    heading.appendChild(title);
    header.appendChild(heading);
    const newChatButton = createElement("button", "cw-close cw-new-chat", "+");
    newChatButton.type = "button";
    newChatButton.hidden = true;
    newChatButton.setAttribute("aria-label", "New chat");
    newChatButton.title = "Start a new chat";
    const stopButton = createElement("button", "cw-close cw-stop", "Stop");
    stopButton.type = "button";
    stopButton.hidden = true;
    stopButton.setAttribute("aria-label", "Stop reply");
    header.appendChild(newChatButton);
    header.appendChild(stopButton);
    header.appendChild(closeButton);

    const messages = createElement("div", "cw-messages");
    messages.setAttribute("role", "log");
    messages.setAttribute("aria-label", "Conversation");
    messages.setAttribute("aria-live", "off");
    const liveStatus = createElement("div", "cw-sr-only");
    liveStatus.setAttribute("role", "status");
    liveStatus.setAttribute("aria-live", "polite");
    const jumpButton = createElement("button", "cw-jump", "↓ Latest reply");
    jumpButton.type = "button"; jumpButton.hidden = true;
    const errorBox = createElement("div", "cw-error");
    errorBox.setAttribute("role", "status");
    errorBox.hidden = true;

    const form = createElement("form", "cw-form");
    const input = createElement("textarea", "cw-input");
    input.rows = 1;
    input.maxLength = 32000;
    input.setAttribute("aria-label", "Your message");
    const send = createElement("button", "cw-send", "↑");
    send.type = "submit";
    send.disabled = true;
    send.setAttribute("aria-label", "Send message");
    form.appendChild(input);
    form.appendChild(send);

    panel.appendChild(header);
    panel.appendChild(messages);
    panel.appendChild(jumpButton);
    panel.appendChild(liveStatus);
    panel.appendChild(errorBox);
    panel.appendChild(form);
    panel.appendChild(createElement("div", "cw-powered", "AI assistant · Check the sources for details"));
    root.appendChild(panel);
    root.appendChild(launcher);

    let config = Object.assign({}, defaultConfig, options);
    let chatHistory = [];
    let sending = false;
    let welcomeRow = null;
    let abortController = null;
    let pendingFrame = null;
    let pendingContent = "";
    let sessionId = null;
    let sessionToken = null;
    let historyKey = null;
    let activeTurn = null;
    let nativeTurns = [];
    let nativePoll = null;
    let nativeEpoch = 0;
    let destroyed = false;
    let errorKind = "";
    let sessionInitializing = false;
    let renderingHistory = false;
    let renderSignature = "";
    let experience = {};
    let experienceActions = [];
    let leadState = { status: "idle" };
    let retryAction = null;
    let errorText = "";
    let reactFrame = null;
    let reactReady = false;
    let reactOrigin = "";
    let reactNonce = "";
    let viewFrame = null;
    let messageSequence = 0;
    const productResults = new Map();
    const pendingProducts = new Set();
    const acknowledged = new Set();

    function publishView() {
      if (!reactReady || !reactFrame || destroyed || viewFrame) return;
      viewFrame = window.requestAnimationFrame(function () {
        viewFrame = null;
        const visibleMessages = Array.from(messages.querySelectorAll(".cw-message")).map(function (row) {
          const value = Object.assign({}, row.__chatPresentation || {});
          const turnId = row.dataset.turnId;
          if (turnId) {
            value.id = turnId + "-" + value.role;
            value.turn_id = turnId;
            value.status = row.dataset.status;
            const turn = nativeTurns.find(function (item) { return item.turn_id === turnId; });
            if (turn && value.role === "assistant") {
              value.status = turn.status;
              value.needs_ack = nativeComplete(turn) && turn.delivery !== "browser_confirmed" && !acknowledged.has(turnId);
            }
            value.products = productResults.get(turnId) || [];
          }
          return value;
        });
        reactFrame.contentWindow.postMessage({ channel: "chatbot-assistant-ui-v1", nonce: reactNonce, action: "snapshot", snapshot: {
          messages: visibleMessages, running: sending, ready: Boolean(sessionId && sessionToken && !sessionInitializing), native: config.nativeSessionV1,
          error: errorText, canRetry: Boolean(retryAction), open: root.classList.contains("cw-open"), standalone: Boolean(options.standalone),
          config: { botName: config.botName, welcomeMessage: config.welcomeMessage, primaryColor: config.primaryColor, accentColor: config.accentColor, placeholderText: config.placeholderText, botAvatarUrl: config.botAvatarUrl },
          experience: experience, actions: experienceActions, lead: leadState,
        } }, reactOrigin);
      });
    }

    async function experienceRequest(path, payload) {
      const response = await fetch(apiBaseUrl + "/public/widget/" + encodeURIComponent(botId) + "/experience" + path, payload ? {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({}, payload, nativeCredential())),
      } : {});
      if (!response.ok) throw new Error("This action is unavailable. Please try again.");
      return response.json();
    }

    async function loadProducts(turnId, attempt) {
      if (!experience.enabled || !experience.product_cards_enabled || !turnId || productResults.has(turnId) || pendingProducts.has(turnId)) return;
      const credentialSession = sessionId;
      if (!credentialSession || !sessionToken) return;
      pendingProducts.add(turnId);
      try {
        const result = await experienceRequest("/products/for-turn", { turn_id: turnId });
        if (destroyed || sessionId !== credentialSession) return;
        if (result.pending && (attempt || 0) < 3) window.setTimeout(function () { if (!destroyed && sessionId === credentialSession) void loadProducts(turnId, (attempt || 0) + 1); }, [150, 350, 700][attempt || 0]);
        else if (!result.pending) { productResults.set(turnId, Array.isArray(result.products) ? result.products : []); publishView(); }
      }
      catch (error) { /* Product cards are optional; the saved answer remains available. */ }
      finally { pendingProducts.delete(turnId); }
    }

    async function handleViewMessage(event) {
      const data = event.data;
      if (!reactFrame || event.source !== reactFrame.contentWindow || event.origin !== reactOrigin || !data || data.channel !== "chatbot-assistant-ui-v1" || data.nonce !== reactNonce || destroyed) return;
      if (data.action === "ready") { reactReady = true; panel.classList.add("cw-react-ready"); publishView(); return; }
      if (!reactReady) return;
      if (data.action === "send" && typeof data.text === "string" && data.text.length <= 32000 && !sending && !sessionInitializing) { input.value = data.text; void sendMessage(); }
      else if (data.action === "close") closeButton.click();
      else if (data.action === "new-chat" && config.nativeSessionV1) newChatButton.click();
      else if (data.action === "cancel" && config.nativeSessionV1) stopButton.click();
      else if (data.action === "retry" && retryAction) retryAction();
      else if (data.action === "lead" && experience.enabled && experience.lead_form_enabled && sessionId && sessionToken && leadState.status !== "sending") {
        leadState = { status: "sending" }; publishView();
        try { await experienceRequest("/leads", data.payload || {}); leadState = { status: "saved" }; }
        catch (error) { leadState = { status: "error", message: "Could not save your details. Please try again." }; }
        publishView();
      } else if (data.action === "rendered" && typeof data.turnId === "string" && typeof data.text === "string" && data.text.length <= 100000) {
        const turn = nativeTurns.find(function (item) { return item.turn_id === data.turnId; });
        if (!turn || !turn.answer) return;
        if (data.firstVisible && !nativeTiming(turn.turn_id).first_visible_ms) nativeTiming(turn.turn_id, { first_visible_ms: Date.now() });
        if (data.complete && nativeComplete(turn) && !acknowledged.has(turn.turn_id)) {
          acknowledged.add(turn.turn_id);
          const timing = nativeTiming(turn.turn_id);
          try { await nativeRequest("ack", { turn_id: turn.turn_id, answer: turn.answer, rendered_text: data.text, rendered_at_ms: Date.now(), first_visible_ms: timing.first_visible_ms || null, submitted_at_ms: timing.submitted_at_ms || null }); }
          catch (error) { acknowledged.delete(turn.turn_id); }
        }
      }
    }

    function initializeReactView() {
      if (options.renderer === "legacy" || !window.crypto || !window.crypto.randomUUID) return;
      try {
        reactOrigin = new URL(options.rendererOrigin || scriptOrigin || window.location.origin).origin;
        if (!/^https?:/.test(reactOrigin)) return;
        reactNonce = window.crypto.randomUUID();
        reactFrame = document.createElement("iframe");
        reactFrame.className = "cw-react-frame";
        reactFrame.title = "Chat with " + config.botName;
        reactFrame.setAttribute("allow", "clipboard-write");
        reactFrame.setAttribute("referrerpolicy", "no-referrer");
        reactFrame.src = reactOrigin + "/embed/chat/" + encodeURIComponent(botId) + "#" + new URLSearchParams({ parentOrigin: window.location.origin, nonce: reactNonce }).toString();
        const style = document.createElement("style");
        style.textContent = ".cw-react-frame{display:none;border:0;width:100%;height:100%;min-height:0;background:#fff}.cw-react-ready>:not(.cw-react-frame){display:none!important}.cw-react-ready>.cw-react-frame{display:block;flex:1}.cw-root.cw-standalone{position:fixed;inset:0;z-index:100;background:#f5f7f6;display:grid;place-items:center}.cw-standalone>.cw-launcher{display:none}.cw-standalone>.cw-panel{position:relative;inset:auto;width:min(760px,100%);height:100dvh;max-height:100dvh;border-radius:0;opacity:1;visibility:visible;pointer-events:auto;transform:none;box-shadow:0 0 45px #163b3412}";
        shadow.appendChild(style);
        panel.appendChild(reactFrame);
        window.addEventListener("message", handleViewMessage);
      } catch (error) { /* The original widget remains available if the enhanced view cannot load. */ }
    }

    function storeValue(key, value) {
      if (!storage) return;
      try { if (value === null) storage.removeItem(key); else storage.setItem(key, value); }
      catch (error) { /* Storage limits must not interrupt the live reply. */ }
    }

    function setOpen(open) {
      root.classList.toggle("cw-open", open);
      panel.inert = !open;
      panel.setAttribute("aria-hidden", String(!open));
      launcher.setAttribute("aria-expanded", String(open));
      launcher.setAttribute("aria-label", open ? "Close chat" : "Open chat");
      publishView();
      if (open) {
        window.requestAnimationFrame(function () {
          if (!destroyed && root.classList.contains("cw-open")) {
            if (reactReady) reactFrame.contentWindow.postMessage({ channel: "chatbot-assistant-ui-v1", nonce: reactNonce, action: "focus" }, reactOrigin);
            else input.focus();
          }
        });
        scrollToBottom(false);
      }
      else launcher.focus();
    }

    jumpButton.addEventListener("click", function () { scrollToBottom(true); });
    messages.addEventListener("scroll", function () {
      jumpButton.hidden = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 120;
    });
    panel.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
    });

    function saveHistory() {
      if (storage && historyKey) {
        storeValue(historyKey, JSON.stringify(chatHistory));
      }
    }

    function scrollToBottom(force) {
      const distanceFromBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight;
      if (force || distanceFromBottom < 120) {
        messages.scrollTop = messages.scrollHeight;
        jumpButton.hidden = true;
      }
    }

    function addMessage(message, persist) {
      const row = createElement("div", "cw-message cw-message-" + message.role);
      row.__chatPresentation = Object.assign({ id: "message-" + (++messageSequence) }, message);
      if (message.turn_id) row.dataset.turnId = message.turn_id;
      const stack = createElement("div", "cw-stack");
      const bubble = createElement("div", "cw-bubble");
      bubble.textContent = message.content;
      const timestamp = message.created_at || new Date().toISOString();
      const time = createElement("div", "cw-time", formatTime(timestamp));
      stack.appendChild(bubble);
      stack.appendChild(time);
      row.appendChild(stack);
      messages.appendChild(row);
      if (!renderingHistory) scrollToBottom(true);

      if (persist) {
        chatHistory.push(message);
        saveHistory();
      }
      publishView();
      return row;
    }

    function updateMessage(row, content) {
      const bubble = row && row.querySelector(".cw-bubble");
      if (bubble) {
        const followReply = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 120;
        bubble.textContent = content;
        if (row.__chatPresentation) row.__chatPresentation.content = content;
        publishView();
        if (followReply) scrollToBottom(true);
        else jumpButton.hidden = false;
      }
    }

    function scheduleMessageUpdate(row, content) {
      pendingContent = content;
      if (pendingFrame) {
        return;
      }
      pendingFrame = window.requestAnimationFrame(function () {
        pendingFrame = null;
        updateMessage(row, pendingContent);
      });
    }

    function flushMessageUpdate(row, content) {
      if (pendingFrame) {
        window.cancelAnimationFrame(pendingFrame);
        pendingFrame = null;
      }
      updateMessage(row, content);
    }

    function renderSources(row, sources) {
      const stack = row && row.querySelector(".cw-stack");
      if (!stack) return;
      const existing = stack.querySelector(".cw-sources");
      if (existing) existing.remove();
      const links = sourceLinks(sources);
      if (!links.length) return;
      const box = createElement("div", "cw-sources");
      box.appendChild(createElement("div", "cw-sources-title", "Sources"));
      const linkRow = createElement("div", "cw-source-links");
      links.forEach(function (item) {
        const link = createElement(item.url ? "a" : "span", "cw-source-link", item.label);
        if (item.url) {
          link.href = item.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
        } else { link.title = "No public source link is available"; }
        linkRow.appendChild(link);
      });
      box.appendChild(linkRow);
      stack.insertBefore(box, stack.querySelector(".cw-time"));
    }

    function finalizeAssistantMessage(row, content, sources) {
      const bubble = row && row.querySelector(".cw-bubble");
      if (!bubble) return;
      const followReply = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 120;
      const visibleSources = presentedSources(content, sources, config.nativeSessionV1);
      renderSafeMarkdown(bubble, content, verifiedUrlSet(visibleSources));
      row.__chatPresentation = Object.assign({}, row.__chatPresentation, { content: content, sources: visibleSources });
      publishView();
      renderSources(row, visibleSources);
      const stack = row.querySelector(".cw-stack");
      const priorCopy = stack.querySelector(".cw-copy");
      if (priorCopy) priorCopy.remove();
      const copy = createElement("button", "cw-copy", "Copy answer");
      copy.type = "button";
      copy.addEventListener("click", async function () {
        try {
          await navigator.clipboard.writeText(String(content));
          copy.textContent = "Copied";
          liveStatus.textContent = "Answer copied.";
        } catch (error) {
          copy.textContent = "Select the answer to copy";
          liveStatus.textContent = "Clipboard unavailable. Select the answer text to copy it.";
        }
      });
      stack.appendChild(copy);
      if (!renderingHistory && followReply) scrollToBottom(true);
    }

    function recentHistory() {
      return chatHistory.slice(-8).map(function (message) {
        return {
          role: message.role,
          content: message.content,
        };
      });
    }

    function setConfig(nextConfig) {
      config = Object.assign({}, config, normalizeConfig(nextConfig), options);
      root.style.setProperty("--cw-primary", config.primaryColor);
      root.style.setProperty("--cw-accent", config.accentColor);
      const wasOpen = root.classList.contains("cw-open");
      root.className = "cw-root " + (config.position === "bottom-left" ? "cw-bottom-left" : "cw-bottom-right") + (wasOpen ? " cw-open" : "");
      if (options.standalone) root.classList.add("cw-standalone");
      panel.setAttribute("aria-label", config.botName);
      titleName.textContent = config.botName;
      titleStatus.textContent = "AI assistant · Product guidance";
      input.placeholder = config.placeholderText;
      launcher.textContent = "";
      const launcherIcon = createElement("span");
      launcherIcon.innerHTML = iconSvg(config.launcherIcon);
      launcher.appendChild(launcherIcon);
      launcher.appendChild(createElement("span", "", config.launcherText));
      avatar.textContent = "";
      const avatarUrl = safeHttpUrl(config.botAvatarUrl);
      if (avatarUrl) {
        const image = document.createElement("img");
        image.alt = "";
        image.src = avatarUrl;
        avatar.appendChild(image);
      } else {
        avatar.innerHTML = iconSvg(config.launcherIcon);
      }
      if (!chatHistory.length) {
        if (!welcomeRow) {
          welcomeRow = addMessage({ role: "assistant", content: config.welcomeMessage }, false);
          welcomeRow.classList.add("cw-welcome");
        } else {
          const bubble = welcomeRow.querySelector(".cw-bubble");
          if (bubble) {
            bubble.textContent = config.welcomeMessage;
            welcomeRow.__chatPresentation.content = config.welcomeMessage;
          }
        }
      }
      publishView();
    }

    function restoreHistory() {
      try {
        chatHistory = storage ? JSON.parse(storage.getItem(historyKey) || "[]") : [];
      } catch (error) {
        chatHistory = [];
      }

      if (chatHistory.length) {
        messages.textContent = "";
        welcomeRow = null;
        chatHistory.forEach(function (message) {
          const row = addMessage(message, false);
          if (message.role === "assistant") {
            finalizeAssistantMessage(row, message.content, Array.isArray(message.sources) ? message.sources : []);
            void loadProducts(message.turn_id);
          }
        });
      }
    }

    function setError(message, retry, kind) {
      errorText = message || "";
      retryAction = retry || null;
      publishView();
      errorKind = message ? (kind || "general") : "";
      errorBox.textContent = "";
      errorBox.hidden = !message;
      if (!message) return;
      errorBox.appendChild(document.createTextNode(message));
      if (retry) {
        const retryButton = createElement("button", "cw-retry", config.nativeSessionV1 ? "Check again" : "Retry");
        retryButton.type = "button";
        retryButton.addEventListener("click", retry);
        errorBox.appendChild(retryButton);
      }
    }

    function updateSendState() {
      send.disabled = sending || sessionInitializing || !sessionId || !sessionToken || !input.value.trim();
      input.disabled = sending || sessionInitializing;
      messages.setAttribute("aria-busy", String(sending));
      titleStatus.textContent = sending ? "Preparing your reply…" : sessionInitializing ? "Connecting…" : "AI assistant · Product guidance";
      publishView();
    }

    function newTurnId() {
      if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
      if (config.nativeSessionV1 && window.crypto && window.crypto.getRandomValues) {
        const bytes = window.crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
        return hex.slice(0, 8) + "-" + hex.slice(8, 12) + "-" + hex.slice(12, 16) + "-" + hex.slice(16, 20) + "-" + hex.slice(20);
      }
      return "turn-" + Date.now() + "-" + Math.random().toString(16).slice(2);
    }

    async function sendMessage(retryTurn) {
      if (config.nativeSessionV1) return sendNativeMessage();
      const message = retryTurn ? retryTurn.message : input.value.trim();
      if (!message || sending || sessionInitializing || !sessionId || !sessionToken) return;

      const history = retryTurn ? retryTurn.history : recentHistory();
      const turnId = retryTurn ? retryTurn.turnId : newTurnId();
      const userMessage = {
        role: "user",
        turn_id: turnId,
        content: message,
        created_at: retryTurn ? retryTurn.createdAt : new Date().toISOString(),
      };
      const userRow = retryTurn ? retryTurn.userRow : addMessage(userMessage, false);
      const turn = { message: message, history: history, turnId: turnId, userRow: userRow, createdAt: userMessage.created_at };
      activeTurn = turn;

      sending = true;
      input.value = "";
      input.style.height = "auto";
      setError("");
      updateSendState();
      const typing = addMessage({ role: "assistant", content: "" }, false);
      userRow.dataset.turnId = turnId;
      typing.dataset.turnId = turnId;
      typing.querySelector(".cw-bubble").innerHTML =
        '<span class="cw-typing"><span class="cw-dot"></span><span class="cw-dot"></span><span class="cw-dot"></span></span>';
      abortController = new AbortController();

      try {
        const response = await fetch(apiBaseUrl + "/public/chat/" + encodeURIComponent(botId) + "/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            session_token: sessionToken,
            turn_id: turnId,
            retry: Boolean(retryTurn),
            message: message,
            history: history,
          }),
          signal: abortController.signal,
        });
        if (!response.ok || !response.body) {
          const detail = await response.text();
          throw new Error(detail || "Chat request failed.");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let reply = "";
        let sources = [];
        let completed = false;
        let serverError = null;
        while (true) {
          const result = await reader.read();
          if (result.done) break;
          buffer += decoder.decode(result.value, { stream: true });
          const events = buffer.split("\n\n");
          buffer = events.pop() || "";
          events.forEach(function (eventText) {
            const dataLine = eventText.split("\n").find(function (line) {
              return line.indexOf("data: ") === 0;
            });
            if (!dataLine) return;
            const payload = safeParseJson(dataLine.slice(6));
            if (payload.type === "token" && payload.token) {
              const piece = String(payload.token);
              const firstVisible = !reply;
              reply += piece;
              // Paint the first approved text immediately; coalesce later batches.
              if (firstVisible) {
                flushMessageUpdate(typing, reply);
              } else {
                scheduleMessageUpdate(typing, reply);
              }
            } else if (payload.type === "sources" && Array.isArray(payload.sources)) {
              sources = payload.sources;
            } else if (payload.type === "done") {
              completed = true;
            } else if (payload.type === "error") {
              serverError = payload.message || "The reply could not be completed.";
            }
          });
        }
        if (serverError || !completed || !reply.trim()) {
          throw new Error(serverError || "The reply was interrupted.");
        }
        flushMessageUpdate(typing, reply);
        finalizeAssistantMessage(typing, reply, sources);
        chatHistory.push(userMessage, {
          role: "assistant",
          turn_id: turnId,
          content: reply,
          sources: sources,
          created_at: new Date().toISOString(),
        });
        saveHistory();
        void loadProducts(turnId);
      } catch (error) {
        typing.remove();
        if (error && error.name === "AbortError") {
          setError("Reply cancelled.", function () { void sendMessage(turn); });
        } else {
          setError("We couldn't complete that reply.", function () { void sendMessage(turn); });
        }
      } finally {
        sending = false;
        abortController = null;
        activeTurn = null;
        updateSendState();
        input.focus();
      }
    }

    launcher.addEventListener("click", function () {
      const open = !root.classList.contains("cw-open");
      if (!open && !config.nativeSessionV1 && abortController) { notifyAbort(activeTurn); abortController.abort(); }
      setOpen(open);
    });
    closeButton.addEventListener("click", function () {
      if (!config.nativeSessionV1 && abortController) { notifyAbort(activeTurn); abortController.abort(); }
      setOpen(false);
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      sendMessage();
    });

    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
        event.preventDefault();
        sendMessage();
      }
    });

    input.addEventListener("input", function () {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 120) + "px";
      updateSendState();
    });

    function notifyAbort(turn) {
      if (!turn || !sessionId || !sessionToken) return;
      fetch(apiBaseUrl + "/public/chat/" + encodeURIComponent(botId) + "/abort", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          session_token: sessionToken,
          turn_id: turn.turnId,
        }),
        keepalive: true,
      }).catch(function () {});
    }

    // Native sessions own semantic history. These local records are delivery
    // recovery hints only and are never supplied as model messages.
    function nativeStorageKey(kind) {
      return "chatbot-widget-native-" + kind + "-" + apiBaseUrl + "-" + botId;
    }

    function nativeCredential() {
      return { session_id: sessionId, session_token: sessionToken };
    }

    function nativeTiming(turnId, fields) {
      const key = nativeStorageKey("timing") + "-" + sessionId + "-" + turnId;
      const value = storage ? safeParseJson(storage.getItem(key) || "") : {};
      if (fields) {
        Object.assign(value, fields);
        storeValue(key, JSON.stringify(value));
      }
      return value;
    }

    async function nativeRequest(action, payload, credential) {
      const response = await fetch(apiBaseUrl + "/public/chat/" + encodeURIComponent(botId) + "/" + action, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign({}, credential || nativeCredential(), payload || {})),
      });
      if (!response.ok) {
        const error = new Error("Session request failed (" + response.status + ").");
        error.status = response.status; throw error;
      }
      return response.status === 204 ? {} : response.json();
    }

    function rememberNativePending(turn) {
      if (!storage) return;
      const key = nativeStorageKey("pending") + "-" + sessionId;
      storeValue(key, turn ? JSON.stringify(turn) : null);
      if (turn && turn.answer) {
        const partialKey = nativeStorageKey("partials") + "-" + sessionId;
        const partials = safeParseJson(storage.getItem(partialKey) || "");
        partials[turn.turn_id] = String(turn.answer);
        // This bounded delivery cache is never submitted as model history.
        const entries = Object.entries(partials).slice(-20);
        storeValue(partialKey, JSON.stringify(Object.fromEntries(entries)));
      }
    }

    function nativeComplete(turn) {
      return turn.status === "completed" || turn.status === "server_complete";
    }

    function nativeActive(turn) {
      return ["accepted", "queued", "running", "retrying"].includes(turn.status);
    }

    function nativeStatusLabel(turn) {
      if (turn.status === "cancelled") return "Reply cancelled.";
      if (turn.status === "uncertain") return "Delivery not confirmed. Checking does not send the question again.";
      if (nativeActive(turn)) return turn.status === "queued" ? "Waiting for a reply…" : "Reply in progress…";
      return "This reply could not be completed.";
    }

    function renderNativeCitations(row, turn) {
      const bubble = row.querySelector(".cw-bubble");
      const references = citationUrlMap(turn.citations);
      const textNodes = [];
      const walker = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        if (!walker.currentNode.parentElement.closest("a, code, pre")) textNodes.push(walker.currentNode);
      }
      textNodes.forEach(function (node) {
        const pattern = /\[ID:\s*(\d+)\s*\]/g;
        const text = node.textContent || "";
        if (!pattern.test(text)) return;
        pattern.lastIndex = 0;
        const fragment = document.createDocumentFragment();
        let position = 0;
        let match;
        while ((match = pattern.exec(text))) {
          fragment.appendChild(document.createTextNode(text.slice(position, match.index)));
          const url = references.get(Number(match[1]));
          const source = (turn.citations || []).find(function (item) { return item && typeof item === "object" && item.citation_index === Number(match[1]) && safeHttpUrl(item.source_url) === url; });
          if (url) {
            const link = createElement("a", "cw-source-link cw-citation", match[0]);
            link.href = url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.setAttribute("aria-label", "Open source: " + (source.title || match[1]));
            link.title = source.title || "Open source";
            fragment.appendChild(link);
          } else {
            fragment.appendChild(document.createTextNode(match[0]));
          }
          position = pattern.lastIndex;
        }
        fragment.appendChild(document.createTextNode(text.slice(position)));
        node.parentNode.replaceChild(fragment, node);
      });
    }

    function renderNativeTurns() {
      const signature = JSON.stringify(nativeTurns);
      if (signature === renderSignature) return;
      renderSignature = signature;
      const oldScroll = messages.scrollTop;
      const atBottom = messages.scrollHeight - oldScroll - messages.clientHeight < 120;
      renderingHistory = true;
      messages.textContent = "";
      welcomeRow = null;
      nativeTurns.forEach(function (turn) {
        const user = addMessage({ role: "user", content: turn.question || "", created_at: turn.created_at }, false);
        user.dataset.turnId = turn.turn_id;
        const row = addMessage({ role: "assistant", content: turn.answer || "", created_at: turn.created_at }, false);
        row.dataset.turnId = turn.turn_id;
        row.dataset.status = turn.status;
        if (turn.answer) {
          finalizeAssistantMessage(row, turn.answer, turn.citations || []);
          renderNativeCitations(row, turn);
        }
        if (nativeComplete(turn)) void loadProducts(turn.turn_id);
        if (!nativeComplete(turn)) {
          row.querySelector(".cw-stack").appendChild(createElement("div", "cw-turn-status", nativeStatusLabel(turn)));
        }
      });
      if (!nativeTurns.length) {
        welcomeRow = addMessage({ role: "assistant", content: config.welcomeMessage }, false);
        welcomeRow.classList.add("cw-welcome");
      }
      renderingHistory = false;
      if (atBottom) scrollToBottom(true); else messages.scrollTop = oldScroll;
    }

    async function reconcileNative() {
      const epoch = nativeEpoch;
      const credential = nativeCredential();
      const state = await nativeRequest("state", {}, credential);
      if (destroyed || epoch !== nativeEpoch) return;
      nativeTurns = Array.isArray(state.turns) ? state.turns : [];
      const partialKey = nativeStorageKey("partials") + "-" + sessionId;
      const partials = storage ? safeParseJson(storage.getItem(partialKey) || "") : {};
      nativeTurns.forEach(function (turn) {
        if (nativeComplete(turn)) delete partials[turn.turn_id];
        else if (!turn.answer && typeof partials[turn.turn_id] === "string") turn.answer = partials[turn.turn_id];
      });
      storeValue(partialKey, JSON.stringify(partials));
      const key = nativeStorageKey("pending") + "-" + sessionId;
      const pending = storage ? safeParseJson(storage.getItem(key) || "") : {};
      if (pending.turn_id && pending.answer) {
        const savedTurn = nativeTurns.find(function (turn) { return turn.turn_id === pending.turn_id; });
        // Text already painted remains visible when an interrupted response was
        // not fully persisted. It is never promoted to a completed/model turn.
        if (savedTurn && !savedTurn.answer && !nativeComplete(savedTurn)) savedTurn.answer = pending.answer;
      }
      if (pending.turn_id && !nativeTurns.some(function (turn) { return turn.turn_id === pending.turn_id; })) {
        nativeTurns.push(Object.assign({}, pending, { status: "uncertain" }));
      } else if (pending.turn_id && nativeTurns.some(function (turn) { return turn.turn_id === pending.turn_id && nativeComplete(turn); })) {
        rememberNativePending(null);
      }
      renderNativeTurns();
      if (errorKind === "recovery" || errorKind === "session") setError("");
      sending = Boolean(state.active_turn_id) || nativeTurns.some(nativeActive);
      activeTurn = sending ? { turnId: state.active_turn_id || nativeTurns.find(nativeActive).turn_id } : null;
      stopButton.hidden = !sending;
      root.dataset.activeTurnId = activeTurn ? activeTurn.turnId : "";
      updateSendState();
      // Acknowledgment is delivery metadata only. It never gates semantic history.
      await Promise.all(nativeTurns.filter(function (turn) {
        return !reactReady && nativeComplete(turn) && turn.answer && turn.delivery !== "browser_confirmed";
      }).map(function (turn) {
        const row = Array.from(messages.querySelectorAll(".cw-message-assistant")).find(function (item) { return item.dataset.turnId === turn.turn_id; });
        const timing = nativeTiming(turn.turn_id);
        return nativeRequest("ack", {
          turn_id: turn.turn_id, answer: turn.answer,
          rendered_text: row ? row.querySelector(".cw-bubble").innerText : "",
          rendered_at_ms: Date.now(),
          first_visible_ms: timing.first_visible_ms || null,
          submitted_at_ms: timing.submitted_at_ms || null,
        }, credential).catch(function () {});
      }));
      window.clearTimeout(nativePoll);
      if (sending) nativePoll = window.setTimeout(function () { void recoverNative(); }, 1500);
      else if (nativeTurns.length) {
        const latest = nativeTurns[nativeTurns.length - 1];
        const hasVisibleSources = sourceLinks(presentedSources(latest.answer, latest.citations, true)).some(function (source) { return source.url; });
        liveStatus.textContent = nativeComplete(latest) ? "Reply ready." + (hasVisibleSources ? " Sources are available in the answer." : "") : nativeStatusLabel(latest);
      } else liveStatus.textContent = "New conversation ready.";
    }

    async function recoverNative() {
      try { await reconcileNative(); }
      catch (error) {
        if (error.status === 401 || error.status === 410) {
          sessionId = null; sessionToken = null; sending = false; activeTurn = null;
          stopButton.hidden = true; updateSendState();
          setError("This conversation is no longer available. Start a new chat to continue.", null, "session");
        } else setError("Connection interrupted. Check the saved reply before sending again.", function () { void recoverNative(); }, "recovery");
      }
    }

    async function initializeNativeSession(fresh) {
      if (sessionInitializing) return;
      sessionInitializing = true; newChatButton.disabled = true;
      newChatButton.hidden = false;
      updateSendState();
      try {
        const saved = !fresh && storage ? safeParseJson(storage.getItem(nativeStorageKey("credential")) || "") : {};
        if (saved.session_id && saved.session_token) {
          sessionId = saved.session_id; sessionToken = saved.session_token;
        } else {
          const response = await fetch(apiBaseUrl + "/public/widget/" + encodeURIComponent(botId) + "/session", { method: "POST" });
          if (!response.ok) throw new Error("Session unavailable.");
          const issued = await response.json();
          sessionId = issued.session_id; sessionToken = issued.session_token;
          storeValue(nativeStorageKey("credential"), JSON.stringify(issued));
        }
        await reconcileNative();
      } catch (error) {
        if (error.status === 401 || error.status === 410) {
          sessionId = null; sessionToken = null;
          setError("This conversation is no longer available. Start a new chat to continue.", null, "session");
        } else setError("The saved conversation is unavailable. Check again or start a new chat.", function () { void initializeNativeSession(false); }, "session");
      } finally {
        sessionInitializing = false; newChatButton.disabled = false; updateSendState();
      }
    }

    async function sendNativeMessage() {
      const message = input.value.trim();
      if (!message || sending || sessionInitializing || !sessionId || !sessionToken) return;
      const epoch = nativeEpoch;
      const credential = nativeCredential();
      const turn = { turn_id: newTurnId(), question: message, answer: "", citations: [], status: "accepted", created_at: new Date().toISOString() };
      nativeTiming(turn.turn_id, { submitted_at_ms: Date.now() });
      rememberNativePending(turn);
      nativeTurns.push(turn);
      renderNativeTurns();
      const row = messages.querySelector('.cw-message-assistant[data-turn-id="' + turn.turn_id + '"]');
      activeTurn = { turnId: turn.turn_id };
      sending = true;
      stopButton.hidden = false;
      liveStatus.textContent = "Preparing your reply.";
      root.dataset.activeTurnId = turn.turn_id;
      input.value = "";
      input.style.height = "auto";
      scrollToBottom(true);
      setError("");
      updateSendState();
      const controller = new AbortController();
      abortController = controller;
      try {
        const response = await fetch(apiBaseUrl + "/public/chat/" + encodeURIComponent(botId) + "/stream", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(Object.assign({}, credential, { turn_id: turn.turn_id, message: message })),
          signal: controller.signal,
        });
        if (!response.ok || !response.body) throw new Error("Chat request not confirmed.");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let terminal = false;
        function frame(eventText) {
          if (epoch !== nativeEpoch || destroyed) return;
          const lines = eventText.split("\n").filter(function (line) { return line.startsWith("data:"); });
          if (!lines.length) return;
          const payload = safeParseJson(lines.map(function (line) { return line.slice(5).trimStart(); }).join("\n"));
          if (payload.turn_id !== turn.turn_id) return;
          if (payload.type === "token" && typeof payload.token === "string") {
            const firstText = !turn.answer && Boolean(payload.token);
            turn.answer += payload.token;
            turn.status = "running";
            updateMessage(row, turn.answer);
            if (!reactReady && firstText && row.querySelector(".cw-bubble").innerText) {
              row.dataset.firstVisibleAt = String(performance.now());
              nativeTiming(turn.turn_id, { first_visible_ms: Date.now() });
            }
            rememberNativePending(turn);
          } else if (payload.type === "sources" && Array.isArray(payload.sources)) {
            turn.citations = payload.sources;
          } else if (payload.type === "queued" || payload.type === "status" || (payload.type === "meta" && (payload.queued === true || payload.buffered === true))) {
            turn.status = payload.type === "queued" || payload.queued === true ? "queued" : "running";
            row.dataset.status = turn.status;
            const notice = row.querySelector(".cw-turn-status");
            if (notice) notice.textContent = turn.status === "queued" ? "Waiting for the knowledge pipeline…" : "Preparing your reply…";
            publishView();
          } else if (payload.type === "done" || payload.type === "error") {
            terminal = true;
            turn.status = payload.type === "done" ? "completed" : "failed";
          }
        }
        while (true) {
          const result = await reader.read();
          buffer += decoder.decode(result.value || new Uint8Array(), { stream: !result.done });
          // Native adapter SSE uses explicit deltas; repeated text stays repeated.
          buffer = buffer.replace(/\r\n/g, "\n");
          let boundary;
          while ((boundary = buffer.indexOf("\n\n")) !== -1) {
            frame(buffer.slice(0, boundary)); buffer = buffer.slice(boundary + 2);
          }
          if (result.done) { if (buffer.trim()) frame(buffer); break; }
        }
        if (!terminal) throw new Error("Reply delivery interrupted.");
      } catch (error) {
        if (epoch === nativeEpoch) {
          turn.status = "uncertain";
          rememberNativePending(turn);
          renderNativeTurns();
          setError("Checking the saved reply. The question will not be sent again.", null, "recovery");
        }
      } finally {
        if (epoch === nativeEpoch && !destroyed) {
          abortController = null;
          await recoverNative();
          input.focus();
        }
      }
    }

    stopButton.addEventListener("click", async function () {
      if (!activeTurn) return;
      try {
        await nativeRequest("abort", { turn_id: activeTurn.turnId });
        setError("Stop requested. Checking the saved result.", null, "recovery");
        if (abortController) abortController.abort();
        else await recoverNative();
      } catch (error) { setError("Could not confirm cancellation. Check the saved reply.", function () { void recoverNative(); }, "recovery"); }
    });

    newChatButton.addEventListener("click", async function () {
      if (!config.nativeSessionV1 || sessionInitializing) return;
      if (activeTurn) {
        try { await nativeRequest("abort", { turn_id: activeTurn.turnId }); }
        catch (error) { setError("Could not confirm the old reply status. Check it before starting a new chat.", function () { void recoverNative(); }); return; }
      }
      nativeEpoch += 1;
      window.clearTimeout(nativePoll);
      if (abortController) abortController.abort();
      abortController = null; activeTurn = null; sessionId = null; sessionToken = null;
      nativeTurns = []; sending = false;
      setError(""); updateSendState();
      await initializeNativeSession(true);
    });

    async function initializeSession() {
      if (config.nativeSessionV1) return initializeNativeSession();
      const sessionKey = "chatbot-widget-credential-" + botId;
      try {
        const saved = storage ? safeParseJson(storage.getItem(sessionKey) || "") : {};
        if (saved.session_id && saved.session_token) {
          sessionId = saved.session_id;
          sessionToken = saved.session_token;
        } else {
          const response = await fetch(
            apiBaseUrl + "/public/widget/" + encodeURIComponent(botId) + "/session",
            { method: "POST" }
          );
          if (!response.ok) throw new Error("Widget session failed.");
          const issued = await response.json();
          sessionId = issued.session_id;
          sessionToken = issued.session_token;
          if (storage) storage.setItem(sessionKey, JSON.stringify(issued));
        }
        historyKey = "chatbot-widget-history-" + botId + "-" + sessionId;
        restoreHistory();
        updateSendState();
      } catch (error) {
        setError("This widget is unavailable on this site.");
      }
    }

    setConfig(config);
    initializeReactView();
    if (options.standalone) setOpen(true);
    experienceRequest("").then(function (value) {
      experience = value || {};
      if (!options.standalone) panel.style.borderRadius = experience.corner_style === "square" ? "4px" : experience.corner_style === "soft" ? "12px" : "24px";
      publishView();
      nativeTurns.filter(nativeComplete).forEach(function (turn) { void loadProducts(turn.turn_id); });
      chatHistory.filter(function (message) { return message.role === "assistant"; }).forEach(function (message) { void loadProducts(message.turn_id); });
      if (experience.enabled) return experienceRequest("/integrations").then(function (actions) {
        experienceActions = Object.entries(actions || {}).filter(function (item) { return item[1] && item[1].enabled && safeHttpUrl(item[1].url); }).map(function (item) { return { kind: item[0], label: item[1].label || (item[0] === "booking" ? "Book an appointment" : "Track an order"), url: safeHttpUrl(item[1].url) }; });
        publishView();
      });
    }).catch(function () { /* Experience tools are optional; keep the established chat flow available. */ });

    fetch(apiBaseUrl + "/public/widget/" + encodeURIComponent(botId))
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Widget config failed.");
        }
        return response.json();
      })
      .then(function (value) { setConfig(value); })
      .catch(function () {
        setConfig(config);
      })
      .then(initializeSession);

    const instance = {
      open: function () {
        setOpen(true);
      },
      close: function () {
        if (!config.nativeSessionV1 && abortController) {
          notifyAbort(activeTurn);
          abortController.abort();
        }
        setOpen(false);
      },
      destroy: function () {
        destroyed = true;
        nativeEpoch += 1;
        window.clearTimeout(nativePoll);
        window.removeEventListener("message", handleViewMessage);
        if (viewFrame) window.cancelAnimationFrame(viewFrame);
        if (abortController) {
          if (!config.nativeSessionV1) notifyAbort(activeTurn);
          abortController.abort();
        }
        host.remove();
        instances.delete(botId);
      },
    };
    instances.set(botId, instance);
    return instance;
  }

  function formatTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function safeParseJson(value) {
    try {
      return JSON.parse(value);
    } catch (error) {
      return {};
    }
  }

  window.ChatbotWidget = {
    init: mount,
  };
  if (window.__CHATBOT_WIDGET_ENABLE_TEST_HOOKS__ === true) {
    window.ChatbotWidget.__test = Object.freeze({
      normalizeConfig: normalizeConfig,
      renderSafeMarkdown: renderSafeMarkdown,
      verifiedUrlSet: verifiedUrlSet,
      sourceLinks: sourceLinks,
      citationUrlMap: citationUrlMap,
      presentedSources: presentedSources,
      safeHttpUrl: safeHttpUrl,
    });
  }

  if (currentScript && currentScript.dataset && currentScript.dataset.botId) {
    const autoInit = function () {
      mount({
        botId: currentScript.dataset.botId,
        apiBaseUrl: currentScript.dataset.apiBaseUrl,
        renderer: currentScript.dataset.renderer,
      });
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", autoInit);
    } else {
      autoInit();
    }
  }
})();
