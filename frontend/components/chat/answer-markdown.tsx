"use client";

import { useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { safeLink, verifiedLinks, type ChatSource } from "./experience-contract";
import "./answer-markdown.css";

// Keep source-aware surfaces restricted to their verified source/CTA links.
// Transcripts do not include source metadata; their ordinary message links are
// still limited to absolute HTTP(S), without credentials or executable HTML.
export function answerMarkdownComponents(allowedLinks?: ReadonlySet<string>): Components {
  return {
    a: ({ href, children }) => {
      const url = safeLink(href);
      return url && (!allowedLinks || allowedLinks.has(url))
        ? <a href={url} target="_blank" rel="noopener noreferrer">{children}</a>
        : <span>{children}</span>;
    },
    img: ({ alt }) => <span>{alt}</span>,
  };
}

export function answerSourceLinks(sources: ChatSource[]): ReadonlySet<string> {
  // An explicitly empty sidecar is still an allowlist: no URLs are attested.
  // Transcript callers without metadata deliberately omit allowedLinks instead.
  return verifiedLinks(sources);
}

export function AnswerMarkdown({ text, allowedLinks, className = "" }: {
  text: string;
  allowedLinks?: ReadonlySet<string>;
  className?: string;
}) {
  const components = useMemo(() => answerMarkdownComponents(allowedLinks), [allowedLinks]);
  return <div data-answer-markdown className={`answer-markdown ${className}`}>
    <ReactMarkdown skipHtml components={components}>{text}</ReactMarkdown>
  </div>;
}
