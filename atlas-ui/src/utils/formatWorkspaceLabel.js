/** Present client ids (slugs) as a readable workspace title. */
export function formatWorkspaceLabel(clientId) {
  if (clientId == null || String(clientId).trim() === "") return "Workspace";
  const raw = String(clientId).trim();
  const parts = raw.split(/[-_\s]+/).filter(Boolean);
  if (!parts.length) return "Workspace";
  if (parts.length > 1) {
    return parts
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(" ");
  }
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

/** Prefer API display_name; otherwise derive a readable label from the folder id. */
export function workspaceDisplayName(clientId, displayNameFromApi) {
  const stored = (displayNameFromApi || "").trim();
  if (stored) return stored;
  return formatWorkspaceLabel(clientId);
}
