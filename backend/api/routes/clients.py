from pathlib import Path

from flask import Response, jsonify, request, send_from_directory

from backend import artifacts
from backend import config
from backend import runner
from backend.api.blueprint import api_bp
from backend.api.helpers import list_workspace_dir_names, reject_client


@api_bp.get("/clients")
def list_clients():
    root: Path = Path(config.CLIENTS_DIR)
    ids = list_workspace_dir_names(root)
    return jsonify(
        clients=[
            {"id": cid, "display_name": artifacts.workspace_display_name(cid)}
            for cid in ids
        ]
    )


@api_bp.post("/clients/<client_id>")
def create_client(client_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    base = Path(config.CLIENTS_DIR) / client_id
    (base / "context").mkdir(parents=True, exist_ok=True)
    (base / "runs").mkdir(parents=True, exist_ok=True)
    body = request.get_json(silent=True) or {}
    logo_b64 = body.get("logo_base64")
    logo_name = str(body.get("logo_filename") or "").strip()
    if logo_b64:
        try:
            artifacts.save_client_logo_from_base64(
                client_id, str(logo_b64), logo_name
            )
        except ValueError as e:
            return jsonify(detail=str(e)), 400
    display_name = str(body.get("display_name") or client_id).strip() or client_id
    artifacts.write_workspace_meta(client_id, {"display_name": display_name})
    return jsonify(created=client_id, display_name=display_name)


@api_bp.get("/clients/<client_id>/logo")
def get_client_logo(client_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    path = artifacts.client_logo_path(client_id)
    if not path:
        return jsonify(detail="no logo"), 404
    return send_from_directory(path.parent, path.name)


@api_bp.put("/clients/<client_id>/logo")
def put_client_logo(client_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    base = Path(config.CLIENTS_DIR) / client_id
    if not base.is_dir():
        return jsonify(detail="client not found"), 404
    body = request.get_json(silent=True) or {}
    logo_b64 = body.get("logo_base64")
    if not logo_b64:
        return jsonify(detail="logo_base64 is required"), 400
    logo_name = str(body.get("logo_filename") or "").strip()
    try:
        stored = artifacts.save_client_logo_from_base64(
            client_id, str(logo_b64), logo_name
        )
    except ValueError as e:
        return jsonify(detail=str(e)), 400
    return jsonify(saved=True, filename=stored)


@api_bp.delete("/clients/<client_id>")
def delete_client(client_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    removed = artifacts.delete_client_workspace(client_id)
    if not removed:
        return jsonify(detail="client not found"), 404
    return jsonify(deleted=True)


@api_bp.get("/clients/<client_id>/context-files")
def list_context_files(client_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    root = Path(config.CLIENTS_DIR) / client_id / "context"
    rows: list[dict] = []
    for spec in artifacts.workspace_artifact_specs(client_id):
        fn = spec["filename"]
        p = root / fn
        rows.append(
            {
                "filename": fn,
                "exists": p.is_file(),
                "bytes": p.stat().st_size if p.is_file() else 0,
            }
        )
    return jsonify(files=rows)


@api_bp.get("/clients/<client_id>/workspace-artifacts")
def list_workspace_artifacts(client_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    root = Path(config.CLIENTS_DIR) / client_id / "context"
    rows: list[dict] = []
    for spec in artifacts.workspace_artifact_specs(client_id):
        fn = spec["filename"]
        p = root / fn
        rows.append(
            {
                **spec,
                "exists": p.is_file(),
                "bytes": p.stat().st_size if p.is_file() else 0,
            }
        )
    return jsonify(artifacts=rows)


@api_bp.post("/clients/<client_id>/workspace-artifacts")
def create_workspace_artifact(client_id: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    body = request.get_json(silent=True) or {}
    slug = body.get("slug") or body.get("filename") or ""
    title = body.get("title") or ""
    description = body.get("description") or ""
    content = body.get("content") or ""
    try:
        entry = artifacts.create_custom_workspace_artifact(
            client_id,
            slug=str(slug),
            title=str(title),
            description=str(description),
            content=str(content),
        )
    except ValueError as e:
        return jsonify(detail=str(e)), 400
    fn = entry["filename"]
    p = Path(config.CLIENTS_DIR) / client_id / "context" / fn
    return jsonify(
        artifact={
            **entry,
            "exists": p.is_file(),
            "bytes": p.stat().st_size if p.is_file() else 0,
        }
    ), 201


@api_bp.delete("/clients/<client_id>/workspace-artifacts/<filename>")
def delete_workspace_artifact(client_id: str, filename: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    if not artifacts.delete_custom_workspace_artifact(client_id, filename):
        return jsonify(detail="artifact not found or not removable"), 404
    return jsonify(deleted=True)


@api_bp.get("/clients/<client_id>/context-files/<filename>")
def get_context_file(client_id: str, filename: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    try:
        text = artifacts.read_context_file(client_id, filename)
    except ValueError as e:
        return jsonify(detail=str(e)), 400
    if text is None:
        return jsonify(filename=filename, content="", exists=False)
    return jsonify(filename=filename, content=text, exists=True)


@api_bp.put("/clients/<client_id>/context-files/<filename>")
def put_context_file(client_id: str, filename: str):
    bad = reject_client(client_id)
    if bad:
        return bad
    body = request.get_json(silent=True) or {}
    content = body.get("content", "")
    try:
        artifacts.write_context_file(client_id, filename, content)
    except ValueError as e:
        return jsonify(detail=str(e)), 400
    return jsonify(saved=True)


@api_bp.get("/clients/<client_id>/context-summary")
def get_context_summary(client_id: str):
    try:
        from backend.context_summary import generate_context_summary

        text = generate_context_summary(client_id)
    except Exception as e:
        return (
            jsonify(
                detail=f"context summary failed: {type(e).__name__}: {e}",
            ),
            500,
        )

    accept = request.headers.get("accept", "")
    if "text/html" in accept and "application/json" not in accept:
        body = (text or "").replace("&", "&amp;").replace("<", "&lt;")
        html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Context · {client_id}</title>
<style>
  body {{ background:#f4f5f7; color:#0a0d18; font-family:-apple-system,Segoe UI,Roboto,sans-serif; margin:0; }}
  .wrap {{ max-width: 760px; margin: 32px auto; padding: 0 20px; }}
  .nav {{ font-size: 12.5px; color: #475569; margin-bottom: 12px; }}
  .nav a {{ color: #1d4ed8; text-decoration: none; }}
  .card {{ background:#fff; border:1px solid #e3e6ec; border-radius:12px; padding:18px 22px; box-shadow: 0 1px 2px rgba(15,23,42,.04); }}
  h1 {{ margin: 0 0 14px; font-size: 20px; letter-spacing: -.012em; }}
  pre {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; color:#0a0d18; margin: 0; }}
</style></head>
<body>
<div class="wrap">
  <div class="nav">For the styled view, open <a href="http://localhost:3000">http://localhost:3000</a> → client → <em>View loaded context</em>.</div>
  <div class="card">
    <h1>Context · {client_id}</h1>
    <pre>{body}</pre>
  </div>
</div>
</body></html>"""
        return Response(html, mimetype="text/html")

    return jsonify(client_id=client_id, summary=text)


@api_bp.post("/clients/<client_id>/pipeline")
def run_full_pipeline(client_id: str):
    body = request.get_json(silent=True) or {}
    topic = body.get("topic") or ""
    final_run_id = runner.run_pipeline(client_id, topic)
    runs_root = Path(config.CLIENTS_DIR) / client_id / "runs"
    if not runs_root.is_dir():
        return jsonify(run_id="", client_id=client_id)

    if isinstance(final_run_id, str) and final_run_id:
        return jsonify(run_id=final_run_id, client_id=client_id)

    child_dirs = sorted(
        (p.name for p in runs_root.iterdir() if p.is_dir()),
        reverse=True,
    )
    newest = child_dirs[0] if child_dirs else ""
    return jsonify(run_id=newest, client_id=client_id)
