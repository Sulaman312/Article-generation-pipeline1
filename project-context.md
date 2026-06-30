# Project Context

This project is a standalone Flask + React app for generating client-specific social media post packages.

Runs on API port **8001** and UI port **3001** (see `.env`).

## App Shape

- Backend: Flask app started from `main.py`.
- Frontend: React app in `atlas-ui/`.
- Workspace/client data: `clients/<client_id>/`.
- Generated run data: `clients/<client_id>/runs/<run_id>/`.
- Client context and template data live under each client folder.

## Run Commands

Backend:

```bash
python3 main.py
```

Frontend:

```bash
cd atlas-ui
npm start
```

Root `.env` holds API keys:

```env
OPENAI_API_KEY=...
FIGMA_ACCESS_TOKEN=...
```

## Social Pipeline

Current active social pipeline order:

```text
client_profile_topic
content_angle_intent
image_prompt
image_generation
image_formats
image_template
captions
review_checklist
```

Important: `image_compose` has been removed from the active flow. Old code still exists but is no longer registered in backend or frontend step order.

## Image Flow

1. OpenAI generates candidate images in Step 4.
2. User selects a primary image.
3. Step 5 `image_formats` creates clean cropped platform images.
4. Step 6 `image_template` applies client-specific template assets and text.
5. Captions and review happen after template application.

Platform dimensions:

```text
Instagram: 1080 x 1350
LinkedIn: 1200 x 628
Facebook: 1200 x 630
```

Resize behavior:

- Uses crop mode now.
- No blurred side fill.
- Step 5 should not show logo/text/template.
- Template elements should appear only after Step 6 `Save & apply`.

## Template Storage

Client template folder:

```text
clients/<client_id>/templates/social_post/
```

Template config:

```text
clients/<client_id>/templates/social_post/template.json
```

Template assets:

```text
clients/<client_id>/templates/social_post/assets/
```

For Arsuno proof-of-concept:

```text
clients/arsuno/templates/social_post/template.json
clients/arsuno/templates/social_post/assets/
```

## Template Schema

The renderer supports two schemas:

1. Old proof-of-concept schema:
   - `logo`
   - `card`
   - `text`

2. New Figma-imported schema:
   - `formats.<platform>.layers[]`
   - Each layer can be:
     - `asset`
     - `text`
     - `shape`

Real client templates should use the Figma-imported `layers` schema.

## Figma Importer

CLI script:

```bash
python3 scripts/import_figma_template.py
```

It:

- Lists clients.
- Prompts for client number.
- Prompts for Figma link.
- Prompts for template folder name, default `social_post`.
- Fetches Figma file.
- Finds platform frames.
- Ignores `GENERATED_BG`.
- Exports `[ASSET]` layers as PNGs.
- Converts `[TEXT]` layers into text JSON.
- Converts simple solid-fill layers into shape JSON.
- Writes `template.json` and asset PNGs.

Requires:

```env
FIGMA_ACCESS_TOKEN=...
```

## Designer Figma Requirements

One frame per platform per template:

```text
Instagram — 1080 x 1350
LinkedIn — 1200 x 628
Facebook — 1200 x 630
```

Frame names can be descriptive, but should include platform names, e.g.:

```text
Instagram — Contrat de Prévoyance
LinkedIn — Contrat de Prévoyance
Facebook — Contrat de Prévoyance
```

Layer naming:

```text
GENERATED_BG
[ASSET] logo
[ASSET] badge
[ASSET] icon-name
[TEXT] headline
[TEXT] subline
```

`GENERATED_BG` is ignored because OpenAI provides the generated background image.

All layers above the generated background are imported.

## Current Figma Importer Notes

The importer previously misdetected `headline` as LinkedIn because it matched loose substring `li`.

That bug was fixed:

- It now detects actual frame-like containers only.
- It no longer treats arbitrary text nodes as platform frames.
- It prefers platform names like `linkedin`, `facebook`, `instagram`.

If Figma returns `429 Too Many Requests`, wait briefly and rerun the importer.

After importing a new template:

```bash
python3 scripts/import_figma_template.py
```

Then restart Flask:

```bash
python3 main.py
```

Then rerun template step in UI:

```text
Step 6 — Apply client template
Save & apply
```

## Important Files

Backend template renderer:

```text
backend/image_templates.py
```

Figma importer:

```text
backend/integrations/figma_templates.py
scripts/import_figma_template.py
```

Social pipeline registration:

```text
backend/social_pipeline.py
backend/pipelines/__init__.py
atlas-ui/src/constants/socialPipeline.js
```

Image routes:

```text
backend/api/routes/images.py
```

Frontend template placement UI:

```text
atlas-ui/src/components/run/RunView.jsx
atlas-ui/src/components/run/ImageGenerationStep.css
```

## Current State

- Proof-of-concept template application works.
- Figma importer exists and can write template JSON/assets.
- Renderer supports variable number of assets/text boxes/shapes.
- UI placement preview was updated to support imported generic layers.
- Need to re-run importer for Arsuno after the LinkedIn frame detection fix.

## Known Next Steps

- Re-run importer for Arsuno with the latest Figma file.
- Confirm `linkedin` now has imported layers in `template.json`.
- Restart Flask.
- Run a fresh test through Step 5 and Step 6.
- Check final exported images under:

```text
clients/arsuno/runs/<run_id>/images/formats/
```

