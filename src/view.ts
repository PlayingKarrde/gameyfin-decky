import { useEffect, useState } from "react";

/** Which page the QAM panel shows. The title bar (cog/back) and the content are rendered
 *  separately by Decky, so they share this tiny store instead of React state. */
export type PanelView = "main" | "settings";

let current: PanelView = "main";
const listeners = new Set<(v: PanelView) => void>();

export function setPanelView(v: PanelView) {
  current = v;
  listeners.forEach((l) => l(v));
}

export function usePanelView(): PanelView {
  const [v, setV] = useState(current);
  useEffect(() => {
    listeners.add(setV);
    setV(current);
    return () => void listeners.delete(setV);
  }, []);
  return v;
}
