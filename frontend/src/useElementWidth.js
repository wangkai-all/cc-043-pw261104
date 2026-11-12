import { useEffect, useState } from "react";

/** Track a DOM node's content width for responsive SVG charts. */
export function useElementWidth() {
  const [node, setNode] = useState(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    if (!node) return undefined;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) setWidth(entry.contentRect.width);
    });
    observer.observe(node);
    setWidth(node.clientWidth);
    return () => observer.disconnect();
  }, [node]);

  return [setNode, width];
}
