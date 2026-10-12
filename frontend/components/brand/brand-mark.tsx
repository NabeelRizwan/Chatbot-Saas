import type { CSSProperties } from "react";

import { cn } from "@/lib/utils";

type BrandMarkProps = {
  className?: string;
  size?: number;
};

export function BrandMark({ className, size = 24 }: BrandMarkProps) {
  const style: CSSProperties = {
    width: size,
    height: size,
    maxWidth: "100%",
    maxHeight: "100%",
    display: "inline-block",
    flexShrink: 0,
    backgroundColor: "currentColor",
    mask: "url('/brand/signal-mark.png') center / contain no-repeat",
    WebkitMask: "url('/brand/signal-mark.png') center / contain no-repeat",
  };

  return <span aria-hidden="true" data-brand="signal" className={cn("align-middle", className)} style={style} />;
}
