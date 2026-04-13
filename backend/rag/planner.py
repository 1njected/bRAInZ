"""Multi-pass pentest plan generator grounded in the knowledge base."""

from __future__ import annotations
import asyncio
import datetime
import json
import logging
from pathlib import Path

from rag.search import VectorIndex, semantic_search
from utils import slug

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pass 1 — Engagement analysis
# ---------------------------------------------------------------------------

_ANALYSIS_SYSTEM = """You are a senior penetration tester. Analyse the engagement description and extract structured parameters.

Output ONLY valid JSON (no markdown fences) with these keys:
{
  "engagement_type": "short label, e.g. Active Directory Red Team / Web App / Cloud / Internal Network",
  "target_summary": "one sentence describing the target",
  "tech_stack": ["technology1", "technology2"],
  "key_attack_surfaces": ["surface1", "surface2"],
  "scope_notes": "brief scope / constraints or empty string"
}"""


async def _pass1_analyse(description: str, llm) -> dict:
    prompt = f"Engagement description:\n{description}"
    raw = await llm.complete(_ANALYSIS_SYSTEM, prompt, max_tokens=512)
    # Strip markdown fences if the model adds them
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except Exception:
        log.warning("Pass 1 JSON parse failed, using fallback: %s", raw[:200])
        return {
            "engagement_type": "Penetration Test",
            "target_summary": description[:200],
            "tech_stack": [],
            "key_attack_surfaces": [],
            "scope_notes": "",
        }


# ---------------------------------------------------------------------------
# Pass 2 — Knowledge base retrieval
# ---------------------------------------------------------------------------

async def _pass2_retrieve(params: dict, llm, vector_index: VectorIndex, index, data_dir: Path) -> list[dict]:
    eng = params.get("engagement_type", "penetration test")
    tech = " ".join(params.get("tech_stack", []))
    surfaces = " ".join(params.get("key_attack_surfaces", []))

    sub_queries = [
        f"{eng} enumeration techniques",
        f"{eng} exploitation",
        f"{tech} vulnerabilities attacks" if tech else f"{eng} vulnerabilities",
        f"post exploitation {eng}",
        f"tools {eng} {surfaces}",
        f"reconnaissance OSINT {eng}",
        f"privilege escalation {eng}",
        f"lateral movement {eng}",
    ]

    async def _search(q: str) -> list[dict]:
        try:
            return await semantic_search(
                query=q,
                llm=llm,
                vector_index=vector_index,
                index=index,
                data_dir=data_dir,
                top_k=8,
            )
        except Exception:
            return []

    all_results = []
    batches = await asyncio.gather(*[_search(q) for q in sub_queries])
    for batch in batches:
        all_results.extend(batch)

    # Deduplicate by item_id, keep highest score
    best: dict[str, dict] = {}
    for r in all_results:
        iid = r["item_id"]
        if iid not in best or r["score"] > best[iid]["score"]:
            best[iid] = r

    ranked = sorted(best.values(), key=lambda x: -x["score"])
    return ranked[:25]


# ---------------------------------------------------------------------------
# Pass 3 — Draft plan
# ---------------------------------------------------------------------------

_DRAFT_SYSTEM = """You are a senior penetration tester writing a comprehensive pentest plan grounded in the provided knowledge base.

Produce a complete, structured plan in Markdown using EXACTLY this structure:

# Pentest Plan: {TARGET}

## Engagement Overview
Bullet list: type, target, scope constraints, key attack surfaces.

## Reconnaissance Checklist
- [ ] OSINT tasks (company info, employees, emails)
- [ ] DNS, certificate transparency, ASN enumeration
- [ ] Technology fingerprinting
- [ ] Specific recon steps for this engagement type
Add at least 10 actionable checklist items.

## Attack Phase Todos
### Phase 1: Enumeration
- [ ] specific enumeration steps

### Phase 2: Initial Access / Exploitation
- [ ] specific exploitation steps

### Phase 3: Post-Exploitation
- [ ] privilege escalation steps
- [ ] lateral movement steps
- [ ] persistence, data collection

Add at least 8 items per phase.

## Tools
Markdown table: | Tool | Purpose | Key Usage / Flags |
Include tools from the knowledge base that are relevant. At least 8 tools.

## Payload & Command Reference
Fenced code blocks with actual commands, one-liners, and payloads.
Group by phase/purpose with comments.

## Library References
List EVERY knowledge base source you drew from as:
- **[Title]** — one sentence explaining why it is relevant

---
Be concrete and specific. Favour tools and techniques explicitly mentioned in the knowledge base over generic advice."""


async def _pass3_draft(description: str, params: dict, results: list[dict], llm) -> str:
    target = params.get("target_summary", description[:100])
    context_parts = [
        f"[{r['title']}]\n{r['content'][:4000]}"
        for r in results
    ]
    context = "\n\n---\n\n".join(context_parts)

    eng_json = json.dumps(params, indent=2)
    prompt = (
        f"Engagement parameters:\n{eng_json}\n\n"
        f"Original description:\n{description}\n\n"
        f"Knowledge base content:\n\n{context}"
    )
    system = _DRAFT_SYSTEM.replace("{TARGET}", target)
    return await llm.complete(system, prompt, max_tokens=8000)


# ---------------------------------------------------------------------------
# Pass 4 — Tool & command enrichment
# ---------------------------------------------------------------------------

_ENRICH_SYSTEM = """You are a senior penetration tester. You have a draft pentest plan and additional tool/command references from the knowledge base.

Your task: enrich the **Tools** table and **Payload & Command Reference** section with specific tool names, exact flags, and one-liner commands from the additional references.

Rules:
- Do NOT change the Engagement Overview, Recon Checklist, or Attack Phase Todos sections.
- Only update Tools and Payload & Command Reference.
- Add rows to the Tools table for any relevant tools found in the additional references that are not already listed.
- Add concrete commands and one-liners to the Command Reference, grouped under clear headings.
- Return the COMPLETE updated plan (all sections)."""


async def _pass4_enrich(draft: str, params: dict, llm, vector_index: VectorIndex, index, data_dir: Path) -> str:
    eng = params.get("engagement_type", "penetration test")
    surfaces = " ".join(params.get("key_attack_surfaces", []))

    try:
        tool_results = await semantic_search(
            query=f"tools commands payloads one-liners {eng} {surfaces}",
            llm=llm,
            vector_index=vector_index,
            index=index,
            data_dir=data_dir,
            top_k=10,
        )
    except Exception:
        tool_results = []

    if not tool_results:
        return draft

    tool_context = "\n\n---\n\n".join(
        f"[{r['title']}]\n{r['content'][:3000]}"
        for r in tool_results
    )
    prompt = (
        f"Draft plan:\n\n{draft}\n\n"
        f"---\n\nAdditional tool/command references from knowledge base:\n\n{tool_context}"
    )
    return await llm.complete(_ENRICH_SYSTEM, prompt, max_tokens=8000)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def generate_plan(
    description: str,
    llm,
    vector_index: VectorIndex,
    index,
    data_dir: Path,
) -> dict:
    """Run the 4-pass pipeline. Returns {slug, title, content, generated}."""
    log.info("Planner pass 1: analysing engagement")
    params = await _pass1_analyse(description, llm)

    log.info("Planner pass 2: retrieving knowledge base (%d sub-queries)", 8)
    results = await _pass2_retrieve(params, llm, vector_index, index, data_dir)
    log.info("Planner pass 2: retrieved %d unique items", len(results))

    log.info("Planner pass 3: drafting plan")
    draft = await _pass3_draft(description, params, results, llm)

    log.info("Planner pass 4: enriching tools and commands")
    final = await _pass4_enrich(draft, params, llm, vector_index, index, data_dir)

    # Save
    title = params.get("target_summary", description[:60])
    plan_slug = slug(description[:60], max_len=50)
    now = datetime.datetime.utcnow().isoformat() + "Z"

    plan_dir = data_dir / "plans" / plan_slug
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "PLAN.md").write_text(final, encoding="utf-8")
    (plan_dir / ".meta.json").write_text(
        json.dumps({"title": title, "generated": now, "description": description}),
        encoding="utf-8",
    )

    log.info("Planner: saved plan to %s", plan_dir)
    return {"slug": plan_slug, "title": title, "content": final, "generated": now}
