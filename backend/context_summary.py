"""One-page context map for a client (runs before pipeline)."""

import json
import re
from datetime import datetime
from pathlib import Path

from . import artifacts
from . import config


def _client_context_path(client_id: str) -> Path:
    """clients/<client_id>/context"""
    return config.CLIENTS_DIR / Path(client_id) / "context"


_CONTEXT_MANIFEST = json.loads(
    '["context.md","personas.md","brand_voice.md","writing_guidelines.md","cta_guidelines.md","internal_links.md"]'
)
assert len(_CONTEXT_MANIFEST) == 6


def _blocks_from_combined(combined: str) -> dict[str, str]:
    """Split artifacts.load_context() output into filename -> body."""
    if not combined or not combined.strip():
        return {}
    blocks: dict[str, str] = {}
    pattern = re.compile(r"^=== (.+?) ===\s*\n", re.MULTILINE)
    positions = list(pattern.finditer(combined))
    for i, m in enumerate(positions):
        name = m.group(1).strip()
        start = m.end()
        end = positions[i + 1].start() if i + 1 < len(positions) else len(combined)
        blocks[name] = combined[start:end].strip()
    return blocks


def _not_provided(body: str, *, treat_placeholder: bool = True) -> bool:
    if not body or not body.strip():
        return True
    if treat_placeholder and "[NOT YET PROVIDED]" in body:
        return True
    return False


def _extract_company_name(md: str) -> str:
    m = re.search(r"Company Name:\s*(\S+)", md)
    if m:
        return m.group(1).strip().rstrip("|,")
    m = re.search(r"^#\s+([^—\n]+)", md)
    if m:
        return m.group(1).replace("— context", "").strip()
    return ""


def _extract_value_prop(md: str) -> str:
    m = re.search(
        r"###\s*2\.\s*Core Value Proposition\s*\n+(.+?)(?=\n###|\n## |\Z)",
        md,
        re.DOTALL | re.IGNORECASE,
    )
    chunk = m.group(1) if m else md
    chunk = re.sub(r"^→[^\n]+\n?", "", chunk, flags=re.MULTILINE)
    chunk = chunk.strip()
    if not chunk:
        return ""
    para = re.split(r"\n\s*\n", chunk)[0]
    text = re.sub(r"\s+", " ", para)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"])", text)
    return " ".join(parts[:2]).strip() if parts else ""


def _feature_title_from_line(rest: str) -> str:
    rest = rest.strip()
    for stop in (
        " Deploy ",
        " Automates ",
        " Moves ",
        " Accelerates ",
        " Automatically ",
        " What it does:",
        " —",
    ):
        if stop in rest:
            rest = rest.split(stop)[0]
            break
    rest = rest.split("—")[0].strip()
    if len(rest) > 72:
        rest = rest[:69].rsplit(" ", 1)[0] + "..."
    return rest


def _extract_main_features(md: str, limit: int = 3) -> list[str]:
    feats: list[str] = []
    for m in re.finditer(
        r"(?:🤖|📄|📊|🔍|✍)\s*([^🤖📄📊🔍✍\n]+)",
        md,
    ):
        title = _feature_title_from_line(m.group(1))
        if title and title not in feats:
            feats.append(title)
        if len(feats) >= limit:
            break
    if len(feats) < limit:
        for m in re.finditer(
            r"###\s*Feature\s*\d+:\s*([^\n]+)", md, re.IGNORECASE
        ):
            name = _feature_title_from_line(m.group(1))
            if name and name not in feats:
                feats.append(name)
            if len(feats) >= limit:
                break
    return feats[:limit]


def _extract_icp_line(md: str) -> str:
    head = md.split("Trigger Conditions", 1)[0]
    m = re.search(
        r"Primary ICP:?\s*\n((?:\s*-\s+[^\n]+(?:\n|$))+)",
        head,
        re.IGNORECASE | re.DOTALL,
    )
    block = m.group(1) if m else ""
    bullets = re.findall(r"^[\s\t]*-\s+([^\n]+)", block, re.MULTILINE)
    if bullets:
        cleaned = []
        for b in bullets[:5]:
            b = b.strip()
            if "Trigger Conditions" in b:
                b = b.split("Trigger Conditions")[0].strip().rstrip(":").strip()
            if b:
                cleaned.append(b)
        return "; ".join(cleaned) if cleaned else ""
    return ""


def _extract_persona_names(md: str) -> list[str]:
    names: list[str] = []
    for m in re.finditer(r'##\s+Persona\s+\d+:\s*"([^"]+)"', md, re.IGNORECASE):
        n = m.group(1).strip()
        if n and n not in names:
            names.append(n)
    if not names:
        for m in re.finditer(
            r'##\s+PERSONA\s+\d+\s*\n+\s*"([^"]+)"', md, re.IGNORECASE
        ):
            n = m.group(1).strip()
            if n and n not in names:
                names.append(n)
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _extract_voice_attributes(md: str) -> list[str]:
    """Four Core Voice Attributes (Confident/Clear/Human/Practical pairs)."""
    m = re.search(
        r"Four Core Voice Attributes:\s*(.+?)(?=\n###|\n## |\Z)",
        md,
        re.DOTALL | re.IGNORECASE,
    )
    chunk = m.group(1) if m else md
    pairs = re.findall(
        r"\b(Confident,\s*Not\s+Arrogant|Clear,\s*Not\s+Dumbed\s+Down|Human,\s*Not\s+Corporate|Practical,\s*Not\s+Theoretical)\b",
        chunk,
        re.IGNORECASE,
    )
    canonical = [
        "Confident, Not Arrogant",
        "Clear, Not Dumbed Down",
        "Human, Not Corporate",
        "Practical, Not Theoretical",
    ]
    if len(pairs) >= 4:
        return pairs[:4]
    found = []
    for label in canonical:
        if re.search(re.escape(label.split(",")[0]), chunk, re.I):
            found.append(label)
    return found if found else canonical


def _extract_banned_words(md: str) -> list[str]:
    words: list[str] = []
    m = re.search(
        r"Words like\s+(.+?)\s+are overused",
        md,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        for q in re.findall(r'"([^"]+)"', m.group(1)):
            w = q.strip().rstrip(",").strip()
            if w and w not in words:
                words.append(w)
    m2 = re.search(r"Cut:\s*((?:\s*\"[^\"]+\"[,\s]*)+)", md)
    if m2:
        for q in re.findall(r'"([^"]+)"', m2.group(1)):
            w = q.strip().rstrip(",").strip()
            if w and w not in words:
                words.append(w)
    return words


def _extract_cta_philosophy(md: str) -> str:
    m = re.search(
        r"###\s*1\.\s*CTA Philosophy\s*\n+([\s\S]+?)(?=\n###|\n## |\Z)",
        md,
        re.IGNORECASE,
    )
    chunk = (m.group(1) if m else md).strip()
    chunk = re.sub(r"\s+", " ", chunk)
    parts = re.split(r"(?<=[.!?])\s+", chunk)
    return " ".join(parts[:2]).strip() if parts else ""


def _extract_cluster_names(md: str) -> list[str]:
    names: list[str] = []
    parts = re.split(r"^## CLUSTER \d+\s*$", md, flags=re.MULTILINE)[1:]
    for block in parts:
        title_line = ""
        for line in block.split("\n"):
            s = line.strip()
            if not s or s.startswith("|"):
                continue
            if "—" in s and not s.startswith("####"):
                title_line = s
                break
        if not title_line:
            continue
        title_line = re.sub(r"^#+\s*", "", title_line)
        title_line = re.sub(
            r"^[\U0001f300-\U0001ffff\u2600-\u27bf]+\s*",
            "",
            title_line,
        )
        main = title_line.split("—")[0].strip()
        if main:
            names.append(main)
    return names[:7]


def generate_context_summary(client_id: str) -> str:
    """Build a one-page markdown map of all standard context files for a client."""
    ts = datetime.now().isoformat()

    combined_topic = artifacts.load_context(client_id, "topic_card")
    combined_brief = artifacts.load_context(client_id, "assignment_brief")
    combined_draft = artifacts.load_context(client_id, "draft")
    combined_final = artifacts.load_context(client_id, "final_output")

    ctx = _blocks_from_combined(combined_topic).get("context.md", "")
    personas = _blocks_from_combined(combined_brief).get("personas.md", "")
    draft_blocks = _blocks_from_combined(combined_draft)
    brand = draft_blocks.get("brand_voice.md", "")
    writing = draft_blocks.get("writing_guidelines.md", "")
    final_blocks = _blocks_from_combined(combined_final)
    cta = final_blocks.get("cta_guidelines.md", "")
    internal = final_blocks.get("internal_links.md", "")

    # COMPANY OVERVIEW (context.md)
    if _not_provided(ctx):
        co_name = "[NOT PROVIDED]"
        value_prop = "[NOT PROVIDED]"
        features_txt = "[NOT PROVIDED]"
        icp_txt = "[NOT PROVIDED]"
    else:
        co_name = _extract_company_name(ctx) or "[NOT PROVIDED]"
        vp = _extract_value_prop(ctx)
        value_prop = vp if vp else "[NOT PROVIDED]"
        feats = _extract_main_features(ctx)
        features_txt = (
            "\n  ".join(f"- {f}" for f in feats) if feats else "[NOT PROVIDED]"
        )
        icp = _extract_icp_line(ctx)
        icp_txt = icp if icp else "[NOT PROVIDED]"

    # PERSONAS
    if _not_provided(personas):
        persona_lines = "  [NOT PROVIDED]"
    else:
        pnames = _extract_persona_names(personas)
        if not pnames:
            persona_lines = "  [NOT PROVIDED]"
        else:
            persona_lines = "\n".join(f"  - {n}" for n in pnames)

    # BRAND VOICE
    if _not_provided(brand):
        voice_lines = "  [NOT PROVIDED]"
    else:
        attrs = _extract_voice_attributes(brand)
        voice_lines = "\n".join(f"  - {a}" for a in attrs)

    # BANNED WORDS
    if _not_provided(writing):
        banned_txt = "[NOT PROVIDED]"
    else:
        banned = _extract_banned_words(writing)
        banned_txt = ", ".join(banned) if banned else "[NOT PROVIDED]"

    # CTA
    if _not_provided(cta):
        cta_txt = "[NOT PROVIDED]"
    else:
        cta_txt = _extract_cta_philosophy(cta) or "[NOT PROVIDED]"

    # CLUSTERS
    if _not_provided(internal):
        cluster_lines = "  [NOT PROVIDED]"
    else:
        clusters = _extract_cluster_names(internal)
        if clusters:
            cluster_lines = "\n".join(
                f"  {i + 1}. {name}" for i, name in enumerate(clusters[:7])
            )
        else:
            cluster_lines = "  [NOT PROVIDED]"

    summary = f"""---CONTEXT SUMMARY START---
CLIENT: {client_id}
GENERATED: {ts}

COMPANY OVERVIEW:
  Name: {co_name}
  Value Prop: {value_prop}
  Main Features:
  {features_txt}
  Key Customers: {icp_txt}

AUDIENCE PERSONAS:
{persona_lines}

BRAND VOICE (4 Core Attributes):
{voice_lines}

BANNED WORDS (Do not use):
{banned_txt}

CTA PHILOSOPHY:
{cta_txt}

CONTENT CLUSTERS (Internal Linking):
{cluster_lines}

---CONTEXT SUMMARY END---
"""
    return summary


if __name__ == "__main__":
    summary = generate_context_summary("arsuno")
    print(summary)
