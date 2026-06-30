import { useState } from "react";
import * as api from "../../services/api";
import { useToast } from "../../context/ToastContext";
import "./DeleteWorkspaceButton.css";

function IconTrash(props) {
  return (
    <svg
      className="delete-workspace-btn-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...props}
    >
      <path d="M3 6h18" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6M14 11v6" />
    </svg>
  );
}

export default function DeleteWorkspaceButton({
  client,
  onDeleted,
  className = "delete-workspace-btn",
}) {
  const { toast } = useToast();
  const [deleting, setDeleting] = useState(false);

  async function handleClick() {
    if (!onDeleted || !client) return;
    const ok = window.confirm(
      `Delete workspace "${client}"?\n\nThis permanently removes:\n• All runs and artifacts\n• All context files\n\nThis cannot be undone.`
    );
    if (!ok) return;
    const typed = window.prompt(
      `Type the workspace id "${client}" exactly to confirm deletion:`,
      ""
    );
    if (typed !== client) {
      if (typed != null && typed !== "")
        window.alert("Workspace id did not match. Nothing was deleted.");
      return;
    }
    setDeleting(true);
    try {
      await api.deleteClient(client);
      onDeleted();
    } catch (e) {
      const msg = e?.message || String(e);
      toast(msg, { variant: "error", duration: 12000 });
    } finally {
      setDeleting(false);
    }
  }

  return (
    <button
      type="button"
      className={className}
      disabled={deleting}
      onClick={handleClick}
      title="Delete this workspace permanently"
    >
      <IconTrash />
      {deleting ? "Deleting…" : "Delete workspace"}
    </button>
  );
}
