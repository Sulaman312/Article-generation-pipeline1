"""Extract actionable fields from client context files into structured dicts."""

from pathlib import Path
import re

from . import config


def _read(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _persona_names_from_text(personas_text: str) -> list[str]:
    names: list[str] = []
    for m in re.finditer(
        r'##\s+Persona\s+\d+:\s*"([^"]+)"',
        personas_text,
        re.IGNORECASE,
    ):
        n = m.group(1).strip()
        if n and n not in names:
            names.append(n)
    if not names:
        for m in re.finditer(
            r"Persona Name:\s*([^\n]+)",
            personas_text,
            re.IGNORECASE,
        ):
            n = m.group(1).strip()
            if n and n not in names:
                names.append(n)
    return names


def _voice_attributes(brand_text: str) -> list[str]:
    m = re.search(
        r"Four Core Voice Attributes:\s*(.+?)(?=\n###|\n## |\Z)",
        brand_text,
        re.DOTALL | re.IGNORECASE,
    )
    chunk = m.group(1) if m else brand_text
    found = re.findall(
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
    if len(found) >= 4:
        return found[:4]
    out = []
    for label in canonical:
        if re.search(re.escape(label.split(",")[0]), chunk, re.I):
            out.append(label)
    return out if out else canonical


def _hype_banned_words(guidelines_text: str) -> list[str]:
    words: list[str] = []
    m = re.search(
        r"Words like\s+(.+?)\s+are overused",
        guidelines_text,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        for q in re.findall(r'"([^"]+)"', m.group(1)):
            w = q.strip().rstrip(",").strip()
            if w:
                words.append(w)
    return words


def _vocabulary_pairs(guidelines_text: str) -> tuple[list[str], list[str]]:
    """Parse Instead of / Use table from Preferred Words section (single-line export)."""
    do_not: list[str] = []
    do_write: list[str] = []
    if "Preferred Words & Phrases" not in guidelines_text:
        return do_not, do_write
    section = guidelines_text.split("Preferred Words & Phrases", 1)[1]
    section = section.split("### Tone-Setting")[0]
    line = re.sub(r"\s+", " ", section).strip()
    if "Instead of... Use..." in line:
        rest = line.split("Instead of... Use...", 1)[1].strip()
    else:
        rest = line

    pairs = [
        ("Leverage", "Use / Apply / Put to work"),
        ("Utilize", "Use"),
        ("Revolutionary / Game-changing", "Practical / Effective / Proven"),
        ("AI solution", "AI system / AI automation / custom AI"),
        ("Implement", "Build / Deploy / Set up"),
        ("Cutting-edge", "Modern / Advanced / Purpose-built"),
        ("Synergy", "Collaboration / Alignment"),
        ("Seamless", "Smooth / Integrated / Frictionless"),
        ("Unlock potential", "Achieve more / Scale faster / Do more"),
        ("Empower", "Help / Enable / Allow"),
        ("Digital transformation", "Operational improvement / Process automation"),
    ]
    for a, b in pairs:
        if a in rest or a.split()[0] in rest:
            do_not.append(a)
            do_write.append(b)
    return do_not, do_write


def _step_5_writing_supplement(client_id: str) -> dict:
    """Banned words, personas, vocabulary — used by pipeline prompt alongside brand_voice."""
    context_path = config.CLIENTS_DIR / client_id / "context"
    banned_words: list[str] = []
    persona_names: list[str] = []
    do_not_write_like: list[str] = []
    do_write_like: list[str] = []

    guidelines_file = context_path / "writing_guidelines.md"
    if guidelines_file.is_file():
        guidelines_text = _read(guidelines_file) or ""
        banned_words = _hype_banned_words(guidelines_text)
        do_not_write_like, do_write_like = _vocabulary_pairs(guidelines_text)
        seen_b = set(banned_words)
        for w in do_not_write_like:
            if w not in seen_b:
                banned_words.append(w)
                seen_b.add(w)

    personas_file = context_path / "personas.md"
    if personas_file.is_file():
        persona_names = _persona_names_from_text(_read(personas_file) or "")[:3]

    return {
        "banned_words": banned_words,
        "persona_names": persona_names,
        "do_not_write_like": do_not_write_like,
        "do_write_like": do_write_like,
    }


def extract_for_step_5(client_id: str) -> dict:
    """
    Extract brand voice attributes WITH instruction text from brand_voice.md.
    Generic parsing that works for ANY company.
    Captures: name, instruction, right example, wrong example.
    """
    brand_file = config.CLIENTS_DIR / client_id / "context" / "brand_voice.md"
    context_file = config.CLIENTS_DIR / client_id / "context" / "context.md"

    company_name = "Unknown"
    if context_file.exists():
        context_text = context_file.read_text(encoding="utf-8")
        match = re.search(r"Company Name:\s*(.+?)(?:\n|$)", context_text)
        if match:
            company_name = match.group(1).strip()
            if " Website:" in company_name:
                company_name = company_name.split(" Website:")[0].strip()

    supplement = _step_5_writing_supplement(client_id)

    if not brand_file.exists():
        return {
            "company_name": company_name,
            "voice_attributes": [],
            "blog_tone": None,
            **supplement,
        }

    brand_text = brand_file.read_text(encoding="utf-8")

    voice_attributes: list[dict] = []

    attribute_sections = re.split(
        r"\n(?=[A-Z][a-z]+(?:, [A-Z])?[^\n]*?\n)",
        brand_text,
    )

    for section in attribute_sections:
        lines = section.split("\n")
        first_line = lines[0] if lines else ""
        name_match = re.search(
            r"^([A-Z][a-z]+(?:, [A-Z][a-z]+)?)\s*$",
            first_line,
            re.MULTILINE,
        )
        if not name_match:
            continue

        attr_name = name_match.group(1).strip()

        instruction_match = re.search(
            rf"{re.escape(attr_name)}\s+(.*?)(?=Right:)",
            section,
            re.DOTALL,
        )
        instruction_text = ""
        if instruction_match:
            instruction_text = instruction_match.group(1).strip()

        right_match = re.search(r'Right:\s*["\']?([^"\'\n]+)["\']?', section)
        right_example = ""
        if right_match:
            right_example = right_match.group(1).strip()

        wrong_match = re.search(r'Wrong:\s*["\']?([^"\'\n]+)["\']?', section)
        wrong_example = ""
        if wrong_match:
            wrong_example = wrong_match.group(1).strip()

        if attr_name and instruction_text and right_example and wrong_example:
            voice_attributes.append(
                {
                    "name": attr_name,
                    "instruction": instruction_text,
                    "right": right_example,
                    "wrong": wrong_example,
                }
            )

    if not voice_attributes:
        for label in _voice_attributes(brand_text):
            voice_attributes.append(
                {
                    "name": label,
                    "instruction": "",
                    "right": "",
                    "wrong": "",
                }
            )

    blog_tone = None
    tone_match = re.search(
        r"\|\s*Blog Posts\s*\|\s*(.+?)\s*\|",
        brand_text,
    )
    if tone_match:
        blog_tone = {
            "type": "Blog Posts",
            "tone": tone_match.group(1).strip(),
        }
    if blog_tone is None:
        prose = re.search(
            r"Blog Posts\s+(.+?)(?=Landing Page|Case Studies|Email)",
            brand_text,
            re.DOTALL | re.IGNORECASE,
        )
        if prose:
            blog_tone = {
                "type": "Blog Posts",
                "tone": re.sub(r"\s+", " ", prose.group(1)).strip(),
            }

    return {
        "company_name": company_name,
        "voice_attributes": voice_attributes,
        "blog_tone": blog_tone,
        **supplement,
    }


def _cluster_titles(links_text: str) -> list[str]:
    names: list[str] = []
    parts = re.split(r"^## CLUSTER \d+\s*$", links_text, flags=re.MULTILINE)[1:]
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


def extract_for_step_7(client_id: str) -> dict:
    """Extract context needed for final output/internal linking."""
    context_path = config.CLIENTS_DIR / client_id / "context"

    clusters: list[str] = []
    cta_philosophy = ""
    cta_examples: list[str] = []

    links_file = context_path / "internal_links.md"
    if links_file.is_file():
        links_text = _read(links_file) or ""
        clusters = _cluster_titles(links_text)

    cta_file = context_path / "cta_guidelines.md"
    if cta_file.is_file():
        cta_text = _read(cta_file) or ""
        m = re.search(
            r"###\s*1\.\s*CTA Philosophy\s*\n+([\s\S]+?)(?=\n###|\n## |\Z)",
            cta_text,
            re.IGNORECASE,
        )
        if m:
            cta_philosophy = re.sub(r"\s+", " ", m.group(1).strip())[:200]
        if "✅ Recommended Phrases" in cta_text:
            ex_section = cta_text.split("✅ Recommended Phrases", 1)[1]
            ex_section = ex_section.split("❌ Phrases to Avoid", 1)[0]
            cta_examples = re.findall(r'"([^"]+)"', ex_section)[:3]

    return {
        "clusters": clusters,
        "cta_philosophy": cta_philosophy,
        "cta_examples": cta_examples,
    }


if __name__ == "__main__":
    result = extract_for_step_5("arsuno")
    print("Brand Voice Extraction:")
    print(f"  Company: {result['company_name']}")
    print(f"  Voice Attributes: {len(result['voice_attributes'])} found\n")
    for attr in result["voice_attributes"]:
        name = attr.get("name", "")
        inst = attr.get("instruction") or ""
        r_ex = attr.get("right") or ""
        w_ex = attr.get("wrong") or ""
        print(f"  {name}")
        print(f"    Instruction: {inst[:80]}{'...' if len(inst) > 80 else ''}")
        print(f"    Right: {r_ex[:60]}{'...' if len(r_ex) > 60 else ''}")
        print(f"    Wrong: {w_ex[:60]}{'...' if len(w_ex) > 60 else ''}\n")
    print(f"  Blog Tone: {result['blog_tone']}")
