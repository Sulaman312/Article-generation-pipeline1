import { useCallback, useEffect, useState } from "react";
import * as api from "../services/api";

const MAX_CACHE_ENTRIES = 40;
const artifactCache = new Map();

function cacheKey(clientId, runId, stepName) {
  return `${clientId}|${runId}|${stepName}`;
}

function cacheGet(key) {
  if (!artifactCache.has(key)) return undefined;
  const value = artifactCache.get(key);
  // Refresh LRU order
  artifactCache.delete(key);
  artifactCache.set(key, value);
  return value;
}

function cacheSet(key, value) {
  if (artifactCache.has(key)) artifactCache.delete(key);
  artifactCache.set(key, value);
  while (artifactCache.size > MAX_CACHE_ENTRIES) {
    const oldest = artifactCache.keys().next().value;
    artifactCache.delete(oldest);
  }
}

export function invalidateArtifactCache(clientId, runId, stepName = null) {
  if (!clientId || !runId) return;
  if (stepName) {
    artifactCache.delete(cacheKey(clientId, runId, stepName));
    return;
  }
  const prefix = `${clientId}|${runId}|`;
  for (const key of artifactCache.keys()) {
    if (key.startsWith(prefix)) artifactCache.delete(key);
  }
}

/** Test helper — clear entire artifact cache. */
export function clearArtifactCacheForTests() {
  artifactCache.clear();
}

/**
 * Fetch a step artifact on demand; cached until invalidated (LRU, max 40).
 */
export function useLazyArtifact(
  clientId,
  runId,
  stepName,
  { enabled = true } = {}
) {
  const key = cacheKey(clientId, runId, stepName);
  const [content, setContentState] = useState(() => {
    if (!(enabled && clientId && runId && stepName)) return "";
    return artifactCache.has(key) ? artifactCache.get(key) : "";
  });
  const [loading, setLoading] = useState(
    () =>
      Boolean(
        enabled && clientId && runId && stepName && !artifactCache.has(key)
      )
  );
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!enabled || !clientId || !runId || !stepName) {
      setLoading(false);
      return undefined;
    }

    const cached = cacheGet(key);
    if (cached != null) {
      setContentState(cached);
      setLoading(false);
      setError(null);
      return undefined;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getArtifact(clientId, runId, stepName)
      .then((value) => {
        if (cancelled) return;
        cacheSet(key, value);
        setContentState(value);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e?.message || String(e));
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [clientId, runId, stepName, enabled, key]);

  const setContent = useCallback(
    (next) => {
      cacheSet(key, next);
      setContentState(next);
    },
    [key]
  );

  return { content, loading, error, setContent };
}
