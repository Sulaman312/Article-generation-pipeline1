# Article Generation Pipeline

Standalone **long-form article** service. Deploy and push to GitHub independently from the post pipeline.

## Ports

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| UI | http://localhost:3000 |

## Setup

```powershell
pip install -r requirements.txt
cd atlas-ui
npm install
cd ..
copy .env.example .env
# Add ANTHROPIC_API_KEY, PERPLEXITY_API_KEY
```

## Run

```powershell
.\start.ps1
```

### If Cursor freezes or crashes

1. **Open one project folder only** — e.g. `article-generation-pipeline`, not all of `Downloads`.
2. **Close other copies** so file watchers are not duplicated.
3. **Restart Cursor** after pulling updates (`.cursorignore` excludes `node_modules/` and `clients/`).
4. Start backend and UI separately if needed:

```powershell
# Terminal 1
$env:API_PORT=8000; python main.py

# Terminal 2
cd atlas-ui
npm start
```

Pipeline step jobs run **in-process** (single Gunicorn worker). Cancel signals abort Claude streaming and interrupt waiting on Perplexity; active in-memory jobs are lost on restart.

## Push to GitHub

```powershell
cd C:\Users\T L S\Downloads\article-generation-pipeline
git init
git add .
git commit -m "Initial commit: article generation pipeline"
gh repo create YOUR_ORG/article-generation-pipeline --private --source=. --push
```

Or create the repo on GitHub first, then:

```powershell
git remote add origin https://github.com/YOUR_ORG/article-generation-pipeline.git
git branch -M main
git push -u origin main
```

## What's included

- Article pipeline only (`backend/pipeline.py`)
- Topic card → research → draft → final output
- Own `clients/` workspace data
- No social / image pipeline code

## Sister repo

`post-generation-pipeline` — social media posts (ports 8001 / 3001).
