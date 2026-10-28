/** Shared UI icons (keep small; avoid pulling icons from LoginPage). */

export function IconLogout({ size = 15 } = {}) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      aria-hidden
    >
      <path
        d="M10 7V6a2 2 0 012-2h7a2 2 0 012 2v12a2 2 0 01-2 2h-7a2 2 0 01-2-2v-1"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M15 12H3m0 0l3-3m-3 3l3 3"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Password visibility toggle: open eye = visible, slashed eye = hidden. */
export function IconEye({ revealed = false, size = 18 } = {}) {
  if (revealed) {
    return (
      <svg viewBox="0 0 24 24" width={size} height={size} fill="none" aria-hidden>
        <path
          d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinejoin="round"
        />
        <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.75" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" aria-hidden>
      <path
        d="M3 3l18 18"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
      <path
        d="M10.6 10.6a2 2 0 002.8 2.8M9.9 5.2A10.4 10.4 0 0112 5c5 0 8.7 3.4 10 7-.4 1.1-1.1 2.3-2 3.3M6.1 6.1C4.4 7.4 3.2 9.1 2 12c1.3 3.6 5 7 10 7 1.7 0 3.3-.4 4.7-1.1"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
