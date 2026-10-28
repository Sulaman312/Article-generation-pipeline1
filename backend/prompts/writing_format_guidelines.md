## Headings

- Use **sentence case** for all headings (H1–H4): capitalize only the first word and proper nouns.
- Product names/modules (WitnessAI, WitnessONE, Observe, Control, Protect, Attack) and acronyms (MCP, AI, NIST, GDPR, etc.) keep their canonical capitalization. **Title case is never allowed.**
- H2s must directly answer a question or support the main title's thesis; each H3 must support its parent H2.
- Number H3s when they form a sequence (steps, phases, ranked items), e.g. "1. Discover all AI activity."
- Every H2 needs one to two sentences of bridging text before its first H3. Never jump straight from H2 to H3.
- The closing H2 must be a unique, topical heading — never "Conclusion," "Final thoughts," "In summary," etc.
- **Table of Contents test:** read all headings in sequence; they should tell one progressive problem-to-solution story without backtracking or repetition.

## Lists and bullets

- Always introduce a bulleted list with a **complete sentence**, not a fragment.
- **One bullet group per section maximum.** If a second is needed, convert it to prose or H4 subheadings.
- Each bullet should be at least **two sentences**. If it needs more than three, promote it to an H4 or paragraph; if it can be said in under two, fold it into a prose list ("these include X, Y, and Z").
- **Never end a section on a bullet list.** Close with at least one sentence of prose.

## Sentences and paragraphs

- No sentence may exceed **30 words**. No paragraph may exceed **4 sentences**. Split at the strongest logical break.
- No sentence may carry more than one subordinate clause. If it needs more than two commas, split it. Apply the read-aloud test (one breath).
- Vary sentence structure and length; avoid mechanically repeating short-sentence-then-long-explanation.
- No trailing filler: every sentence should end on its strongest word; cut closing clauses that add nothing.
- **Repeated openings:** never start three sentences in a row with the same word (« Le… Le… Le… », « Vous… Vous… Vous… »). Reorder the clause, merge two sentences, or open with a connector. The lint blocks runs of three or more.
- **Transition words (Yoast):** at least **30%** of body sentences must include a **Yoast-recognized** transition/connector in the article language. When you split a long idea into short sentences, start follow-ups with connectors so the prose does not read as an unlinked stack.
  - EN examples: however, therefore, for example, in addition, also, next, finally, meanwhile, as a result, because, so, first, then, instead, specifically.
  - FR examples (Yoast-recognized only): en effet, par exemple, donc, ainsi, ensuite, enfin, cependant, toutefois, en revanche, par ailleurs, en outre, en plus, car, parce que, c'est pourquoi, d'abord, puis, également, notamment, autrement dit.
  - **French pitfall:** do **not** rely on « de plus » — Yoast FR does **not** count it. Use « en outre » or « en plus » instead.
  - Do not pad with empty phrases ("It is important to note" / "Il est important de noter"); use real logical connectors only.

## Punctuation

- **No em dashes or en dashes anywhere** (headings, body, CTAs, FAQs, meta titles, meta descriptions). Use commas, colons, sentence breaks, or an ASCII hyphen (-) instead. Never write — or –.
- In CTA markers, the separator must be a **colon**, not an em dash or hyphen.
- Full stops go **outside** link brackets, never inside.

## Structure / BLUF

- **Opening (required):** Immediately after the H1, use this exact order:
  1. Localized takeaways H2 — **English:** `## Key takeaways` · **French:** `## À retenir` (never English labels in a French article). **40–80 words** of **actionable takeaways** as **exactly 3–5 markdown bullets** (required — not prose paragraphs). This is **not** an article summary/recap of sections. Use the **exact** primary keyword once, in the **first bullet**, so it falls inside the first 100 body words. A synonym or a heading does not count. Do **not** title this block `## Summary`.
  2. **Hero image** — `![descriptive alt text](IMAGE: slug-or-description)` on the next line after the takeaways content. Every image's alt text is one meaningful phrase (8 to 15 words) with **no hyphen or dash**; never paste the slug as alt text.
  3. Then the first content H2.
- **FAQ H2 language:** English `## Frequently Asked Questions` · French `## Questions fréquentes`. Match the article language.
- Do **not** put body prose or CTAs between the takeaways image and the first content H2.
- **Never** add another heading titled "Key takeaways", "À retenir", "Summary", "Takeaways", "What you'll learn", "In this article", or similar anywhere later in the article. Opening takeaways appear once at the top only.
- Use **BLUF** (Bottom Line Up Front) in every section: the first sentence or two under any H2 (and the first sentence of every H3) states the main takeaway before supporting detail. No throat-clearing.
- **Heading-Body Contract:** the body must deliver exactly what the heading promises (a "how-to" heading needs steps/numbered guidance, a comparison heading needs comparison, etc.).

## Trust / E-E-A-T (natural, in-body)

- Show **experience** with specific workflows, roles, or situations — not "as experts we believe."
- Show **expertise** with accurate terms, BLUF answers, and real constraints (when something does not apply).
- Show **authoritativeness** with 3–5 inline outbound links to credible sources (from SERP research), woven mid-sentence.
- Show **trust** by stating limits and using **only real, source-backed prices and numbers**. Every concrete price, fee, %, ROI, or numeric claim must come from SERP research / Research Audit approved sources and carry an inline HTTPS citation in the same paragraph. If you cannot cite it, generalize ("fees vary by clinic") or omit the number — never invent.
- Do **not** add a standalone "Why trust us" or "E-E-A-T" section — trust signals live inside normal prose, proof slots, and citations.

## CTAs

- Place **exactly two** CTA blocks per article, never more: one **in between** (at a transition between two H2 sections, after the first content section) and one **at the end** (after the last content section, before the FAQ). **Never** put a CTA in the opening (title, takeaways, hero image, intro) or mid-paragraph.
- Each CTA has **three elements on separate lines**: bold heading, one-to-two-sentence description, and a markdown link with the button label. Preserve the markdown and spacing; do not collapse into one paragraph.
- CTA href comes from the client workspace artifacts: prefer an explicit URL/path in
  `cta_guidelines.md`, otherwise use the live Website from `context.md` with `/contact`
  (e.g. `https://example.com/contact`). Never use `/demo` or `/request-demo`.
- If the workspace `cta_guidelines.md` includes an **HTML CTA Template**, still write the
  three-line markdown CTAs above. Post-processing wraps them in that HTML shell: only the
  headline, body, and button label change per article; CSS and contact URL stay fixed.
