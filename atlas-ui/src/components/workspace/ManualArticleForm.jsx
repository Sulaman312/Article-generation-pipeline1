import { useState } from "react";
import * as api from "../../services/api";
import {
  EMPTY_EDITORIAL_FIELDS,
  EDITORIAL_FIELD_SPECS,
  buildManualInputsPayload,
  hasRequiredTopic,
} from "../../utils/editorialFields";
import "./ManualArticleForm.css";

export default function ManualArticleForm({ client, onOpenRun, onCreated }) {
  const [fields, setFields] = useState(() => EMPTY_EDITORIAL_FIELDS());
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);

  function setField(key, value) {
    setFields((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!hasRequiredTopic(fields) || creating) return;
    setCreating(true);
    setError(null);
    const { manual_inputs } = buildManualInputsPayload(fields);
    try {
      const result = await api.createRun(client, null, { manual_inputs });
      const newId = result?.run_id;
      setFields(EMPTY_EDITORIAL_FIELDS());
      onCreated?.();
      if (newId) onOpenRun?.(newId);
    } catch (err) {
      const msg = err?.message || String(err);
      setError(msg);
    } finally {
      setCreating(false);
    }
  }

  return (
    <form className="manual-article-form" onSubmit={handleSubmit}>
      <div className="manual-article-grid">
        {EDITORIAL_FIELD_SPECS.map((spec) => (
          <div
            key={spec.key}
            className={`manual-article-field${spec.wide ? " manual-article-field--wide" : ""}`}
          >
            <label className="label" htmlFor={`maf-${spec.key}`}>
              {spec.label}
              {spec.required ? (
                <span className="manual-article-req"> *</span>
              ) : null}
            </label>
            {spec.hint ? (
              <p className="manual-article-field-hint">{spec.hint}</p>
            ) : null}
            {spec.wide ? (
              <textarea
                id={`maf-${spec.key}`}
                className="textarea"
                rows={spec.key === "notes" ? 3 : 2}
                value={fields[spec.key]}
                onChange={(ev) => setField(spec.key, ev.target.value)}
                disabled={creating}
              />
            ) : (
              <input
                id={`maf-${spec.key}`}
                className="input"
                type="text"
                value={fields[spec.key]}
                onChange={(ev) => setField(spec.key, ev.target.value)}
                disabled={creating}
              />
            )}
          </div>
        ))}
      </div>

      <div className="manual-article-actions">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!hasRequiredTopic(fields) || creating}
        >
          {creating ? (
            <>
              <span className="spinner spinner-light" /> Creating run…
            </>
          ) : (
            <>+ Create article run</>
          )}
        </button>
        {error ? (
          <span className="manual-article-error" role="alert">
            {error}
          </span>
        ) : null}
      </div>
    </form>
  );
}

