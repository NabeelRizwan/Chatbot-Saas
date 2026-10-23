import { ExternalLink } from "lucide-react";
import { sourceLinks, type ChatSource } from "./experience-contract";

export function SourceLinks({ sources, className = "", linkClassName = "" }: {
  sources: ChatSource[]; className?: string; linkClassName?: string;
}) {
  const links = sourceLinks(sources);
  if (!links.length) return null;
  return <div className={className} aria-label="Sources">{links.map((source) => source.url
    ? <a className={linkClassName} key={source.url} href={source.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={11} />{source.label}</a>
    : <span className={linkClassName} key={"label:" + source.label} title="No public source link is available">{source.label}</span>)}</div>;
}
