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
    placeholderText: "Type your message...",
  };

  function normalizeConfig(payload) {
    return {
      botName: payload.bot_name || payload.botName || defaultConfig.botName,
      welcomeMessage: payload.welcome_message || payload.welcomeMessage || defaultConfig.welcomeMessage,
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

  function createSessionId(botId) {
    const key = "chatbot-widget-session-" + botId;
    const storage = getSessionStorage();
    const existing = storage && storage.getItem(key);
    if (existing) {
      return existing;
    }

    const sessionId =
      (window.crypto && window.crypto.randomUUID && window.crypto.randomUUID()) ||
      "session-" + Date.now() + "-" + Math.random().toString(16).slice(2);
    if (storage) {
      storage.setItem(key, sessionId);
    }
    return sessionId;
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
        border-radius: 18px;
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
        padding: 15px 16px;
        background: linear-gradient(135deg, var(--cw-primary), color-mix(in srgb, var(--cw-primary) 78%, var(--cw-accent)));
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
        padding: 16px;
        background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
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
        border-radius: 16px;
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
        border-bottom-left-radius: 5px;
      }
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

    const apiBaseUrl = "https://chatbot-saas-ai.up.railway.app";
    const sessionId = createSessionId(botId);
    const historyKey = "chatbot-widget-history-" + botId + "-" + sessionId;
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
    const closeButton = createElement("button", "cw-close", "x");
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
    root.appendChild(panel);
    root.appendChild(launcher);

    let config = Object.assign({}, defaultConfig, options);
    let chatHistory = [];
    let sending = false;
    let welcomeRow = null;
    let abortController = null;
    let pendingFrame = null;
    let pendingContent = "";

    function saveHistory() {
      if (storage) {
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
      launcher.innerHTML = iconSvg(config.launcherIcon) + "<span>" + escapeHTML(config.launcherText) + "</span>";
      avatar.innerHTML = config.botAvatarUrl
        ? '<img alt="" src="' + escapeAttribute(config.botAvatarUrl) + '">'
        : iconSvg(config.launcherIcon);
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

    function setError(message) {
      errorBox.textContent = message || "";
      errorBox.hidden = !message;
    }

    function updateSendState() {
      send.disabled = sending || !input.value.trim();
      input.disabled = sending;
    }

    async function sendMessage() {
      const message = input.value.trim();
      if (!message || sending) {
        return;
      }

      sending = true;
      updateSendState();
      input.value = "";
      input.style.height = "auto";
      updateSendState();
      setError("");
      const history = recentHistory();
      addMessage({ role: "user", content: message, created_at: new Date().toISOString() }, true);

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
            message: message,
            history: history,
          }),
          signal: abortController.signal,
        });

        if (!response.ok || !response.body) {
          throw new Error("Streaming chat request failed.");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let reply = "";
        while (true) {
          const result = await reader.read();
          if (result.done) {
            break;
          }
          buffer += decoder.decode(result.value, { stream: true });
          const events = buffer.split("\n\n");
          buffer = events.pop() || "";
          events.forEach(function (eventText) {
            const dataLine = eventText.split("\n").find(function (line) {
              return line.indexOf("data: ") === 0;
            });
            if (!dataLine) {
              return;
            }
            const payload = safeParseJson(dataLine.slice(6));
            if (payload.token) {
              reply += payload.token;
              scheduleMessageUpdate(typing, reply);
            }
          });
        }

        if (!reply.trim()) {
          throw new Error("Empty streamed reply.");
        }
        flushMessageUpdate(typing, reply);

        chatHistory.push({
          role: "assistant",
          content: reply,
          created_at: new Date().toISOString(),
        });
        saveHistory();
      } catch (error) {
        if (error && error.name === "AbortError") {
          typing.remove();
          return;
        }
        try {
          const response = await fetch(apiBaseUrl + "/public/chat/" + encodeURIComponent(botId), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: sessionId,
              message: message,
              history: history,
            }),
          });

          if (!response.ok) {
            throw new Error("Chat request failed.");
          }

          const data = await response.json();
          flushMessageUpdate(typing, data.answer || data.reply || "Sorry, something went wrong. Please try again.");
          chatHistory.push({
            role: "assistant",
            content: data.answer || data.reply || "Sorry, something went wrong. Please try again.",
            created_at: new Date().toISOString(),
          });
          saveHistory();
        } catch (fallbackError) {
          typing.remove();
          setError("Sorry, something went wrong. Please try again.");
        }
      } finally {
        sending = false;
        abortController = null;
        updateSendState();
        input.focus();
      }
    }

    launcher.addEventListener("click", function () {
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

    setConfig(config);
    restoreHistory();

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
          abortController.abort();
        }
        root.classList.remove("cw-open");
      },
      destroy: function () {
        if (abortController) {
          abortController.abort();
        }
        host.remove();
        instances.delete(botId);
      },
    };
    instances.set(botId, instance);
    return instance;
  }

  function escapeHTML(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function escapeAttribute(value) {
    return escapeHTML(value);
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
})();
