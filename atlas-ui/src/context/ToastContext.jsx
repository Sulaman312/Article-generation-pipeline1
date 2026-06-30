import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

const ToastCtx = createContext(null);

function formatToastText(input) {
  if (input == null) return "";
  if (typeof input === "string") return input.trim() || "";
  try {
    return String(input).trim();
  } catch {
    return "";
  }
}

function ToastBanner({ text, variant, durationMs, onDismiss }) {
  const dismissTimer = useRef(null);

  useEffect(() => {
    const ms =
      typeof durationMs === "number" && durationMs > 0 ? durationMs : 8500;
    dismissTimer.current = window.setTimeout(() => onDismiss(), ms);
    return () => {
      if (dismissTimer.current) window.clearTimeout(dismissTimer.current);
    };
  }, [text, durationMs, onDismiss]);

  const cls =
    variant === "success"
      ? "toast-banner toast-banner-success"
      : "toast-banner toast-banner-error";

  return (
    <div className={cls} role={variant === "error" ? "alert" : "status"}>
      <div className="toast-banner-body">{text}</div>
      <button
        type="button"
        className="toast-banner-dismiss btn btn-ghost btn-sm"
        onClick={onDismiss}
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  );
}

export function ToastProvider({ children }) {
  const [toast, setToastState] = useState(null);

  const dismiss = useCallback(() => setToastState(null), []);

  const toastFn = useCallback((message, opts = {}) => {
    const text = formatToastText(message);
    if (!text) return;
    setToastState({
      id: `${Date.now()}-${Math.random()}`,
      text,
      variant: opts.variant ?? "error",
      durationMs: opts.duration,
    });
  }, []);

  const value = { toast: toastFn, dismiss };

  return (
    <ToastCtx.Provider value={value}>
      {children}
      {toast ? (
        <ToastBanner
          key={toast.id}
          text={toast.text}
          variant={toast.variant}
          durationMs={toast.durationMs}
          onDismiss={dismiss}
        />
      ) : null}
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx)
    throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
