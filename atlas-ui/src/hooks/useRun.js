import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as api from "../services/api";

const POLL_ACTIVE_MS = 2500;
const POLL_IDLE_MS = 30000;

/**
 * Single owner for run polling: fast while a step is running, slow when idle,
 * paused while the tab is hidden.
 */
export function useRun(clientId, runId, { onSuccess } = {}) {
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;

  const hasRunningStep = useMemo(() => {
    if (!run?.statuses) return false;
    return Object.values(run.statuses).some((s) => s === "running");
  }, [run?.statuses]);

  const refreshRun = useCallback(async () => {
    if (!clientId || !runId) return null;
    try {
      const r = await api.getRun(clientId, runId);
      setRun(r);
      setError(null);
      onSuccessRef.current?.(r);
      return r;
    } catch (e) {
      setError(e?.message || String(e));
      return null;
    }
  }, [clientId, runId]);

  useEffect(() => {
    if (!clientId || !runId) {
      setRun(null);
      setError(null);
      return undefined;
    }

    let cancelled = false;
    let timerId = null;

    async function tick() {
      if (cancelled || document.visibilityState === "hidden") return;
      await refreshRun();
    }

    function clearTimer() {
      if (timerId != null) {
        window.clearInterval(timerId);
        timerId = null;
      }
    }

    function schedule() {
      clearTimer();
      if (document.visibilityState === "hidden") return;
      const intervalMs = hasRunningStep ? POLL_ACTIVE_MS : POLL_IDLE_MS;
      timerId = window.setInterval(tick, intervalMs);
    }

    tick();
    schedule();

    function onVisibilityChange() {
      if (document.visibilityState === "visible") {
        tick();
        schedule();
      } else {
        clearTimer();
      }
    }

    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      cancelled = true;
      clearTimer();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [clientId, runId, refreshRun, hasRunningStep]);

  return { run, error, refreshRun, hasRunningStep };
}
