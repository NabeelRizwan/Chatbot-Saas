"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { AssistantRuntimeProvider, ComposerPrimitive, MessagePrimitive, ThreadPrimitive, useAuiState, useExternalStoreRuntime, type AppendMessage, type ThreadMessageLike } from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import { ArrowDown, ArrowUp, Check, Copy, ExternalLink, Mail, Plus, Square, X } from "lucide-react";
import { BrandMark } from "@/components/brand/brand-mark";
import { answerMarkdownComponents } from "./answer-markdown";
import { SourceLinks } from "./source-links";
import { displayAnswer, safeLink, verifiedLinks, type BridgeCommand, type ExperienceMessage, type ExperienceSnapshot } from "./experience-contract";
import "./assistant-chat.css";

const SnapshotContext = createContext<{ snapshot: ExperienceSnapshot; command: (command: BridgeCommand) => void } | null>(null);

function useChat() {
  const value = useContext(SnapshotContext);
  if (!value) throw new Error("Chat view requires its transport bridge.");
  return value;
}

function ChatMessage() {
  const { snapshot, command } = useChat();
  const messageId = useAuiState((state) => state.message.id);
  const message = snapshot.messages.find((item) => item.id === messageId);
  const body = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const sentAck = useRef("");
  const firstPaint = useRef(false);
  const links = useMemo(() => verifiedLinks(message?.sources), [message?.sources]);
  const markdownComponents = useMemo(() => answerMarkdownComponents(links), [links]);
  useEffect(() => {
    if (!message?.turn_id || message.role !== "assistant" || !message.content) return;
    const frame = requestAnimationFrame(() => {
      const text = body.current?.innerText || "";
      if (!text) return;
      if (!firstPaint.current || (message.needs_ack && sentAck.current !== message.content)) {
        command({ action: "rendered", turnId: message.turn_id, text, firstVisible: !firstPaint.current, complete: Boolean(message.needs_ack) });
        firstPaint.current = true;
        if (message.needs_ack) sentAck.current = message.content;
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [command, message]);
  if (!message) return null;
  const assistant = message.role === "assistant";
  const active = ["running", "accepted", "queued", "retrying"].includes(message.status || "");
  async function copy() {
    try { await navigator.clipboard.writeText(message!.content); setCopied(true); setCopyError(false); window.setTimeout(() => setCopied(false), 1800); }
    catch { setCopyError(true); }
  }
  return <MessagePrimitive.Root className={`aui-message ${assistant ? "aui-assistant" : "aui-user"}`} data-turn-id={message.turn_id}>
    <div ref={body} className="aui-message-body">
      {message.content ? <MessagePrimitive.Parts components={{ Text: () => <MarkdownTextPrimitive className="aui-markdown" skipHtml components={markdownComponents} /> }} /> : active ? <span className="aui-typing" aria-label="Preparing your reply"><i /><i /><i /></span> : null}
    </div>
    {assistant && active && !message.content && <p role="status" className="aui-turn-notice">{message.status === "queued" ? "Waiting for the knowledge pipeline…" : "Preparing your reply…"}</p>}
    {assistant && <SourceLinks sources={message.sources || []} className="aui-sources" />}
    {assistant && Boolean(message.products?.length) && <div className="aui-products" aria-label="Related products">{message.products!.map((product) => {
      const url = safeLink(product.url); if (!url) return null;
      return <article className="aui-product" key={product.id}>
        {safeLink(product.image_url) && <img src={safeLink(product.image_url)!} alt="" loading="lazy" referrerPolicy="no-referrer" />}
        <div><strong>{product.title}</strong>{product.description && <p>{product.description}</p>}
          {product.price_amount && <span>{product.currency || ""} {product.price_amount}</span>}
          <a href={url} target="_blank" rel="noopener noreferrer">View product <ExternalLink size={12} /></a></div>
      </article>;
    })}</div>}
    {assistant && message.content && !active && <div className="aui-message-tools"><button onClick={() => void copy()} aria-label={copied ? "Answer copied" : "Copy answer"}>{copied ? <Check size={13} /> : <Copy size={13} />}{copied ? "Copied" : "Copy"}</button>{copyError && <span role="status">Select the answer to copy it.</span>}</div>}
    {message.status && !["completed", "server_complete"].includes(message.status) && !active && <p className="aui-turn-notice">{message.status === "cancelled" ? "Reply stopped." : message.status === "uncertain" ? "Checking the saved reply…" : "This reply could not be completed."}</p>}
  </MessagePrimitive.Root>;
}

function LeadForm({ onClose }: { onClose: () => void }) {
  const { snapshot, command } = useChat();
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const nameInput = useRef<HTMLInputElement>(null);
  useEffect(() => { nameInput.current?.focus(); }, []);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const values = new FormData(event.currentTarget);
    command({ action: "lead", payload: { name: values.get("name"), email: values.get("email"), phone: values.get("phone"), message: values.get("message"), consent: values.get("consent") === "on", idempotency_key: idempotencyKey } });
  }
  return <section className="aui-lead" aria-label="Contact form"><div className="aui-lead-heading"><strong>Let’s stay in touch</strong><button onClick={onClose} aria-label="Close contact form"><X size={16} /></button></div>
    {snapshot.lead?.status === "saved" ? <p role="status">Thanks. Your details have been received.</p> : <form onSubmit={submit}>
      <label>Name<input ref={nameInput} name="name" required maxLength={150} autoComplete="name" /></label>
      <label>Email<input name="email" type="email" required maxLength={254} autoComplete="email" /></label>
      <label>Phone <span>(optional)</span><input name="phone" type="tel" maxLength={40} autoComplete="tel" /></label>
      <label>How can we help? <span>(optional)</span><textarea name="message" maxLength={2000} rows={2} /></label>
      <label className="aui-consent"><input name="consent" type="checkbox" required /><span>{snapshot.experience.lead_consent_text || "I agree to be contacted about my enquiry."}</span></label>
      {snapshot.lead?.status === "error" && <p role="alert">{snapshot.lead.message || "Could not save your details. Please try again."}</p>}
      <button className="aui-submit-lead" disabled={snapshot.lead?.status === "sending" || !snapshot.ready} type="submit">{snapshot.lead?.status === "sending" ? "Sending…" : "Send details"}</button>
    </form>}
  </section>;
}

export function AssistantChat({ snapshot, command }: { snapshot: ExperienceSnapshot; command: (command: BridgeCommand) => void }) {
  const [leadOpen, setLeadOpen] = useState(false);
  const contactButton = useRef<HTMLButtonElement>(null);
  const runtime = useExternalStoreRuntime({
    messages: snapshot.messages,
    isRunning: snapshot.running,
    isDisabled: !snapshot.ready,
    convertMessage: (message: ExperienceMessage): ThreadMessageLike => ({ id: message.id, role: message.role, content: displayAnswer(message), createdAt: message.created_at ? new Date(message.created_at) : undefined }),
    onNew: async (message: AppendMessage) => { const text = message.content.filter((part) => part.type === "text").map((part) => part.text).join("\n"); if (text.trim()) command({ action: "send", text }); },
    onCancel: snapshot.native ? async () => { command({ action: "cancel" }); } : undefined,
  });
  const appearance = snapshot.experience;
  const theme = appearance.theme || "light";
  const primary = /^#[0-9a-f]{6}$/i.test(snapshot.config.primaryColor) ? snapshot.config.primaryColor : "#2563eb";
  const rgb = [1, 3, 5].map((index) => parseInt(primary.slice(index, index + 2), 16));
  const bright = (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) / 1000 > 155;
  const style = { "--aui-primary": primary, "--aui-on-primary": bright ? "#101d16" : "#fff", "--aui-accent": /^#[0-9a-f]{6}$/i.test(snapshot.config.accentColor) ? snapshot.config.accentColor : primary, "--aui-radius": appearance.corner_style === "square" ? "3px" : appearance.corner_style === "soft" ? "10px" : "19px", fontFamily: appearance.font_family === "serif" ? "Georgia,serif" : appearance.font_family === "inter" ? "var(--font-inter),system-ui,sans-serif" : "system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" } as CSSProperties;
  const hasUser = snapshot.messages.some((message) => message.role === "user");
  return <SnapshotContext.Provider value={{ snapshot, command }}><AssistantRuntimeProvider runtime={runtime}>
    <ThreadPrimitive.Root className={`aui-shell aui-theme-${theme} aui-density-${appearance.density || "comfortable"}`} style={style} onKeyDown={(event) => { if (event.key === "Escape" && !snapshot.standalone) command({ action: "close" }); }}>
      <header className="aui-header"><div className="aui-avatar">{safeLink(snapshot.config.botAvatarUrl) ? <img src={safeLink(snapshot.config.botAvatarUrl)!} alt="" /> : <BrandMark size={26} />}</div><div className="aui-heading"><strong>{snapshot.config.botName}</strong><span><i />{snapshot.running ? "Preparing your reply…" : snapshot.ready ? "Here to help" : "Connecting…"}</span></div>
        {snapshot.native && <button className="aui-icon-button" onClick={() => command({ action: "new-chat" })} aria-label="Start a new chat" title="New chat"><Plus size={19} /></button>}
        {!snapshot.standalone && <button className="aui-icon-button" onClick={() => command({ action: "close" })} aria-label="Close chat"><X size={19} /></button>}
      </header>
      <ThreadPrimitive.Viewport className="aui-viewport"><ThreadPrimitive.Messages components={{ Message: ChatMessage }} />
        {!hasUser && appearance.enabled && Boolean(appearance.suggested_questions?.length) && <div className="aui-suggestions" aria-label="Suggested questions">{appearance.suggested_questions!.map((question) => <button disabled={!snapshot.ready || snapshot.running} key={question} onClick={() => command({ action: "send", text: question })}>{question}<ArrowUp size={14} /></button>)}</div>}
      </ThreadPrimitive.Viewport>
      <ThreadPrimitive.ScrollToBottom className="aui-jump" aria-label="Scroll to latest reply"><ArrowDown size={14} /> Latest reply</ThreadPrimitive.ScrollToBottom>
      {snapshot.error && <div className="aui-error" role="status">{snapshot.error}{snapshot.canRetry && <button onClick={() => command({ action: "retry" })}>{snapshot.native ? "Check again" : "Retry"}</button>}</div>}
      {leadOpen && <LeadForm onClose={() => { setLeadOpen(false); requestAnimationFrame(() => contactButton.current?.focus()); }} />}
      <div className="aui-actions">{appearance.enabled && appearance.lead_form_enabled && !leadOpen && <button ref={contactButton} onClick={() => setLeadOpen(true)}><Mail size={13} />Contact us</button>}{(snapshot.actions || []).map((action) => { const url = safeLink(action.url); return url ? <a key={action.kind} href={url} target="_blank" rel="noopener noreferrer">{action.label}<ExternalLink size={12} /></a> : null; })}</div>
      <ComposerPrimitive.Root className="aui-composer"><ComposerPrimitive.Input aria-label="Your message" placeholder={snapshot.config.placeholderText} maxLength={32000} className="aui-input" autoFocus />
        {snapshot.running && snapshot.native ? <ComposerPrimitive.Cancel className="aui-send" aria-label="Stop reply"><Square size={16} /></ComposerPrimitive.Cancel> : <ComposerPrimitive.Send className="aui-send" aria-label="Send message"><ArrowUp size={20} /></ComposerPrimitive.Send>}
      </ComposerPrimitive.Root>
      <footer className="aui-footer">AI assistant · Answers based on available information</footer>
    </ThreadPrimitive.Root>
  </AssistantRuntimeProvider></SnapshotContext.Provider>;
}
