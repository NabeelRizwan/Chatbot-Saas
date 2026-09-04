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
    try {
      const parsed = new URL(String(value));
      return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
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
        strong.textContent = match[4];
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
    const urls = new Set();
    (sources || []).forEach(function (source) {
      const sourceUrl = safeHttpUrl(source && source.source_url);
      if (sourceUrl) urls.add(sourceUrl);
      (source && source.cta_links || []).forEach(function (cta) {
        const ctaUrl = safeHttpUrl(cta && cta.url);
        if (ctaUrl) urls.add(ctaUrl);
      });
    });
    return urls;
  }

  function iconSvg(name) {
    if (name === "sparkle") {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.7 5.1L19 10l-5.3 1.9L12 17l-1.7-5.1L5 10l5.3-1.9L12 3zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15z"/></svg>';
    }
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6.5A3.5 3.5 0 0 1 8.5 3h7A3.5 3.5 0 0 1 19 6.5v5A3.5 3.5 0 0 1 15.5 15H11l-4.2 3.6A1 1 0 0 1 5.2 18v-3.2A3.5 3.5 0 0 1 2 11.5v-5z"/></svg>';
  }

  function appendStyles(root) {
    const style = document.createElement("style");
    style.textContent = `
      :host { color-scheme: light dark; }
      * { box-sizing: border-box; }
      .cw-root {
        --cw-primary: #2563eb;
        --cw-accent: #0f172a;
        --cw-bottom: 20px;
        --cw-side: 20px;
        position: fixed;
        z-index: 2147483000;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: #111827;
      }
      .cw-root.cw-bottom-right { right: var(--cw-side); bottom: var(--cw-bottom); }
      .cw-root.cw-bottom-left { left: var(--cw-side); bottom: var(--cw-bottom); }
      .cw-launcher {
        display: inline-flex;
        align-items: center;
        gap: 9px;
        min-width: 58px;
        height: 58px;
        padding: 0 18px;
        border: 0;
        border-radius: 999px;
        background: var(--cw-primary);
        color: #fff;
        cursor: pointer;
        font: 700 14px/1 inherit;
        box-shadow: 0 16px 35px rgba(17, 24, 39, .22);
        transition: transform .2s ease, box-shadow .2s ease, opacity .2s ease;
      }
      .cw-launcher:hover { transform: translateY(-1px); box-shadow: 0 20px 40px rgba(17, 24, 39, .28); }
      .cw-open .cw-launcher { transform: scale(.96); opacity: .92; }
      .cw-launcher svg { width: 22px; height: 22px; fill: currentColor; }
      .cw-panel {
        position: absolute;
        bottom: 74px;
        width: min(390px, calc(100vw - 32px));
        height: min(640px, calc(100vh - 112px));
        display: flex;
        flex-direction: column;
        overflow: hidden;
        border: 1px solid rgba(148, 163, 184, .28);
        border-radius: 20px;
        background: #fff;
        box-shadow: 0 24px 60px rgba(15, 23, 42, .24);
        opacity: 0;
        pointer-events: none;
        transform: translateY(18px) scale(.97);
        transform-origin: bottom right;
        transition: opacity .22s ease, transform .22s ease;
      }
      .cw-bottom-right .cw-panel { right: 0; }
      .cw-bottom-left .cw-panel { left: 0; transform-origin: bottom left; }
      .cw-open .cw-panel { opacity: 1; pointer-events: auto; transform: translateY(0) scale(1); }
      .cw-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 17px 16px;
        background: linear-gradient(135deg, var(--cw-primary), color-mix(in srgb, var(--cw-primary) 72%, var(--cw-accent)));
        color: #fff;
      }
      .cw-avatar {
        width: 38px;
        height: 38px;
        flex: 0 0 auto;
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: rgba(255, 255, 255, .16);
        box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .18);
        overflow: hidden;
      }
      .cw-avatar img { width: 100%; height: 100%; object-fit: cover; }
      .cw-avatar svg { width: 20px; height: 20px; fill: currentColor; }
      .cw-heading {
        display: flex;
        min-width: 0;
        align-items: center;
        gap: 10px;
      }
      .cw-title { min-width: 0; }
      .cw-title strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 15px; }
      .cw-title span { display: block; margin-top: 2px; font-size: 12px; opacity: .84; }
      .cw-close {
        width: 34px;
        height: 34px;
        border: 0;
        border-radius: 999px;
        background: rgba(255, 255, 255, .14);
        color: #fff;
        cursor: pointer;
        font-size: 20px;
        line-height: 1;
      }
      .cw-messages {
        flex: 1;
        overflow-y: auto;
        padding: 18px 16px 12px;
        background: #f8fafc;
      }
      .cw-message {
        display: flex;
        margin: 0 0 12px;
        animation: cw-message-in .18s ease both;
      }
      @keyframes cw-message-in {
        from { opacity: 0; transform: translateY(7px); }
        to { opacity: 1; transform: translateY(0); }
      }
      .cw-message-user { justify-content: flex-end; }
      .cw-bubble {
        max-width: 86%;
        border-radius: 18px;
        padding: 10px 13px;
        font-size: 14px;
        line-height: 1.45;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
      }
      .cw-message-user .cw-bubble { background: var(--cw-primary); color: #fff; border-bottom-right-radius: 5px; }
      .cw-message-assistant .cw-bubble {
        border: 1px solid rgba(148, 163, 184, .28);
        background: #fff;
        color: #111827;
        border-bottom-left-radius: 6px;
        box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
      }
      .cw-bubble p { margin: 0 0 8px; }
      .cw-bubble p:last-child { margin-bottom: 0; }
      .cw-bubble ul, .cw-bubble ol { margin: 5px 0; padding-left: 20px; }
      .cw-bubble li + li { margin-top: 3px; }
      .cw-link { color: var(--cw-primary); text-decoration: underline; text-underline-offset: 2px; }
      .cw-table-wrap { max-width: 100%; overflow-x: auto; margin: 7px 0; }
      .cw-table { border-collapse: collapse; min-width: 100%; font-size: 12px; }
      .cw-table th, .cw-table td { border: 1px solid #cbd5e1; padding: 6px; text-align: left; vertical-align: top; }
      .cw-sources { margin-top: 7px; padding: 9px 10px; border: 1px solid rgba(148, 163, 184, .28); border-radius: 12px; background: rgba(255, 255, 255, .75); }
      .cw-sources-title { margin-bottom: 6px; color: #64748b; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
      .cw-source-links { display: flex; flex-wrap: wrap; gap: 6px; }
      .cw-source-link { display: inline-flex; max-width: 100%; border: 1px solid color-mix(in srgb, var(--cw-primary) 25%, #cbd5e1); border-radius: 999px; padding: 5px 8px; color: var(--cw-primary); background: #fff; font-size: 11px; font-weight: 650; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .cw-stack { max-width: 88%; }
      .cw-message-user .cw-stack { max-width: 86%; }
      .cw-powered { padding: 0 16px 10px; background: #fff; color: #94a3b8; font-size: 10px; text-align: center; }
      .cw-time {
        margin-top: 5px;
        padding: 0 4px;
        color: #94a3b8;
        font-size: 11px;
      }
      .cw-message-user .cw-time { text-align: right; }
      .cw-typing {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        color: #64748b;
      }
      .cw-dot { width: 6px; height: 6px; border-radius: 999px; background: currentColor; animation: cw-pulse 1s infinite ease-in-out; }
      .cw-dot:nth-child(2) { animation-delay: .12s; }
      .cw-dot:nth-child(3) { animation-delay: .24s; }
      @keyframes cw-pulse { 0%, 80%, 100% { opacity: .35; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-3px); } }
      .cw-error {
        margin: 0 16px 12px;
        border-radius: 10px;
        background: #fef2f2;
        color: #b91c1c;
        padding: 9px 10px;
        font-size: 13px;
      }
      .cw-retry { margin-left: 8px; border: 1px solid currentColor; border-radius: 7px; padding: 4px 7px; background: transparent; color: inherit; cursor: pointer; font-weight: 700; }
      .cw-form {
        display: flex;
        align-items: flex-end;
        gap: 8px;
        padding: 12px 13px 13px;
        border-top: 1px solid rgba(148, 163, 184, .24);
        background: #fff;
      }
      .cw-input {
        flex: 1;
        min-height: 42px;
        max-height: 120px;
        resize: none;
        border: 1px solid rgba(148, 163, 184, .45);
        border-radius: 12px;
        padding: 10px 11px;
        font: 14px/1.35 inherit;
        color: #111827;
        background: #fff;
        outline: none;
      }
      .cw-input:focus { border-color: var(--cw-primary); box-shadow: 0 0 0 3px color-mix(in srgb, var(--cw-primary) 18%, transparent); }
      .cw-send {
        width: 42px;
        height: 42px;
        border: 0;
        border-radius: 12px;
        background: var(--cw-primary);
        color: #fff;
        cursor: pointer;
        font-weight: 800;
        transition: opacity .18s ease, transform .18s ease;
      }
      .cw-send:hover:not(:disabled) { transform: translateY(-1px); }
      .cw-send:disabled { cursor: not-allowed; opacity: .55; }
      .cw-input:disabled { cursor: wait; opacity: .72; }
      @media (max-width: 520px) {
        .cw-root {
          --cw-bottom: 14px;
          --cw-side: 14px;
        }
        .cw-panel {
          position: fixed;
          inset: 0;
          width: auto;
          height: auto;
          bottom: 78px;
          border-radius: 0;
        }
        .cw-root.cw-bottom-right, .cw-root.cw-bottom-left { left: 0; right: 0; bottom: 0; }
        .cw-launcher {
          position: fixed;
          right: 14px;
          bottom: 14px;
          height: 56px;
          min-width: 56px;
          padding: 0 16px;
        }
      }
      @media (prefers-color-scheme: dark) {
        .cw-panel, .cw-form { background: #0f172a; border-color: rgba(148, 163, 184, .22); }
        .cw-messages { background: #020617; }
        .cw-message-assistant .cw-bubble { background: #111827; border-color: rgba(148, 163, 184, .24); color: #e5e7eb; }
        .cw-input { background: #111827; border-color: rgba(148, 163, 184, .35); color: #f8fafc; }
      }
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
    const launcher = createElement("button", "cw-launcher");
    launcher.type = "button";
    shadow.appendChild(root);

    const header = createElement("div", "cw-header");
    const heading = createElement("div", "cw-heading");
    const avatar = createElement("div", "cw-avatar");
    avatar.innerHTML = iconSvg(defaultConfig.launcherIcon);
    const title = createElement("div", "cw-title");
    const titleName = createElement("strong", "", defaultConfig.botName);
    const titleStatus = createElement("span", "", "Usually replies instantly");
    const closeButton = createElement("button", "cw-close", "×");
    closeButton.type = "button";
    closeButton.setAttribute("aria-label", "Close chat");
    heading.appendChild(avatar);
    title.appendChild(titleName);
    title.appendChild(titleStatus);
    heading.appendChild(title);
    header.appendChild(heading);
    header.appendChild(closeButton);

    const messages = createElement("div", "cw-messages");
    const errorBox = createElement("div", "cw-error");
    errorBox.hidden = true;

    const form = createElement("form", "cw-form");
    const input = createElement("textarea", "cw-input");
    input.rows = 1;
    const send = createElement("button", "cw-send", "↑");
    send.type = "submit";
    send.disabled = true;
    send.setAttribute("aria-label", "Send message");
    form.appendChild(input);
    form.appendChild(send);

    panel.appendChild(header);
    panel.appendChild(messages);
    panel.appendChild(errorBox);
    panel.appendChild(form);
    panel.appendChild(createElement("div", "cw-powered", "Powered by AI"));
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

    function saveHistory() {
      if (storage && historyKey) {
        storage.setItem(historyKey, JSON.stringify(chatHistory));
      }
    }

    function scrollToBottom(force) {
      const distanceFromBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight;
      if (force || distanceFromBottom < 120) {
        messages.scrollTop = messages.scrollHeight;
      }
    }

    function addMessage(message, persist) {
      const row = createElement("div", "cw-message cw-message-" + message.role);
      const stack = createElement("div", "cw-stack");
      const bubble = createElement("div", "cw-bubble");
      bubble.textContent = message.content;
      const timestamp = message.created_at || new Date().toISOString();
      const time = createElement("div", "cw-time", formatTime(timestamp));
      stack.appendChild(bubble);
      stack.appendChild(time);
      row.appendChild(stack);
      messages.appendChild(row);
      scrollToBottom(true);

      if (persist) {
        chatHistory.push(message);
        saveHistory();
      }
      return row;
    }

    function updateMessage(row, content) {
      const bubble = row && row.querySelector(".cw-bubble");
      if (bubble) {
        bubble.textContent = content;
        scrollToBottom(false);
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
      const seen = new Set();
      const links = [];
      (sources || []).forEach(function (source) {
        (source && source.cta_links || []).forEach(function (cta) {
          const href = safeHttpUrl(cta && cta.url);
          if (href && !seen.has(href)) {
            seen.add(href);
            links.push({ href: href, label: cta.label || "View" });
          }
        });
        const href = safeHttpUrl(source && source.source_url);
        if (href && !seen.has(href)) {
          seen.add(href);
          links.push({ href: href, label: source.title || source.filename || "Source" });
        }
      });
      if (!links.length) return;
      const box = createElement("div", "cw-sources");
      box.appendChild(createElement("div", "cw-sources-title", "Sources"));
      const linkRow = createElement("div", "cw-source-links");
      // Multi-document catalog/comparison answers can legitimately use more
      // than five independently indexed pages. Keep a bounded display while
      // avoiding silent source loss for those answers.
      links.slice(0, 12).forEach(function (item) {
        const link = createElement("a", "cw-source-link", item.label);
        link.href = item.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        linkRow.appendChild(link);
      });
      box.appendChild(linkRow);
      stack.insertBefore(box, stack.querySelector(".cw-time"));
    }

    function finalizeAssistantMessage(row, content, sources) {
      const bubble = row && row.querySelector(".cw-bubble");
      if (!bubble) return;
      renderSafeMarkdown(bubble, content, verifiedUrlSet(sources));
      renderSources(row, sources);
      scrollToBottom(false);
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
      root.className = "cw-root " + (config.position === "bottom-left" ? "cw-bottom-left" : "cw-bottom-right");
      titleName.textContent = config.botName;
      titleStatus.textContent = config.launcherTitle;
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
        } else {
          const bubble = welcomeRow.querySelector(".cw-bubble");
          if (bubble) {
            bubble.textContent = config.welcomeMessage;
          }
        }
      }
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
          addMessage(message, false);
        });
      }
    }

    function setError(message, retry) {
      errorBox.textContent = "";
      errorBox.hidden = !message;
      if (!message) return;
      errorBox.appendChild(document.createTextNode(message));
      if (retry) {
        const retryButton = createElement("button", "cw-retry", "Retry");
        retryButton.type = "button";
        retryButton.addEventListener("click", retry);
        errorBox.appendChild(retryButton);
      }
    }

    function updateSendState() {
      send.disabled = sending || !sessionId || !sessionToken || !input.value.trim();
      input.disabled = sending;
    }

    function newTurnId() {
      return (window.crypto && window.crypto.randomUUID && window.crypto.randomUUID()) ||
        "turn-" + Date.now() + "-" + Math.random().toString(16).slice(2);
    }

    async function sendMessage(retryTurn) {
      const message = retryTurn ? retryTurn.message : input.value.trim();
      if (!message || sending || !sessionId || !sessionToken) return;

      const history = retryTurn ? retryTurn.history : recentHistory();
      const turnId = retryTurn ? retryTurn.turnId : newTurnId();
      const userMessage = {
        role: "user",
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
          content: reply,
          created_at: new Date().toISOString(),
        });
        saveHistory();
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
      if (root.classList.contains("cw-open") && abortController) {
        notifyAbort(activeTurn);
        abortController.abort();
      }
      root.classList.toggle("cw-open");
      if (root.classList.contains("cw-open")) {
        window.setTimeout(function () {
          input.focus();
          scrollToBottom(true);
        }, 80);
      }
    });

    closeButton.addEventListener("click", function () {
      if (abortController) {
        notifyAbort(activeTurn);
        abortController.abort();
      }
      root.classList.remove("cw-open");
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      sendMessage();
    });

    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
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

    async function initializeSession() {
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
    void initializeSession();

    fetch(apiBaseUrl + "/public/widget/" + encodeURIComponent(botId))
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Widget config failed.");
        }
        return response.json();
      })
      .then(setConfig)
      .catch(function () {
        setConfig(config);
      });

    const instance = {
      open: function () {
        root.classList.add("cw-open");
      },
      close: function () {
        if (abortController) {
          notifyAbort(activeTurn);
          abortController.abort();
        }
        root.classList.remove("cw-open");
      },
      destroy: function () {
        if (abortController) {
          notifyAbort(activeTurn);
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
      safeHttpUrl: safeHttpUrl,
    });
  }

  if (currentScript && currentScript.dataset && currentScript.dataset.botId) {
    const autoInit = function () {
      mount({
        botId: currentScript.dataset.botId,
        apiBaseUrl: currentScript.dataset.apiBaseUrl,
      });
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", autoInit);
    } else {
      autoInit();
    }
  }
})();
