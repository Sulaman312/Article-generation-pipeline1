import { useCallback, useEffect, useRef } from "react";

export const SIDEBAR_WIDTH_MIN = 240;
export const SIDEBAR_WIDTH_MAX = 480;
/** Wide enough for full pipeline step labels without manual resize. */
export const SIDEBAR_WIDTH_DEFAULT = 380;

export function readStoredSidebarWidth() {
  try {
    const w = Number.parseInt(localStorage.getItem("cf-sidebar-width"), 10);
    if (
      Number.isFinite(w) &&
      w >= SIDEBAR_WIDTH_MIN &&
      w <= SIDEBAR_WIDTH_MAX
    ) {
      // Bump users still on older narrow defaults to the new default.
      if (w === 272 || w === 300) return SIDEBAR_WIDTH_DEFAULT;
      return w;
    }
  } catch {
    /* ignore */
  }
  return SIDEBAR_WIDTH_DEFAULT;
}

export function useSidebarResize({ enabled, width, onWidthChange, min, max }) {
  const draggingRef = useRef(false);
  const startXRef = useRef(0);
  const startWRef = useRef(0);

  const onPointerDown = useCallback(
    (e) => {
      if (!enabled) return;
      if (e.button !== 0) return;
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      draggingRef.current = true;
      startXRef.current = e.clientX;
      startWRef.current = width;
      document.body.classList.add("sb-resizing");
    },
    [enabled, width]
  );

  useEffect(() => {
    const onPointerMove = (e) => {
      if (!draggingRef.current) return;
      const delta = e.clientX - startXRef.current;
      const next = Math.min(max, Math.max(min, startWRef.current + delta));
      onWidthChange(next);
    };
    const end = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      document.body.classList.remove("sb-resizing");
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      document.body.classList.remove("sb-resizing");
    };
  }, [min, max, onWidthChange]);

  return onPointerDown;
}
