# RAG Searches and Flexibility for Teaser Assessment (Procedures & Guidelines)

This document describes how RAG (Vertex AI Search) is used and how flexible the system is when using procedure and guideline information for teaser-based assessment.

---

## 1. How RAG Search Works

### Single data store, post-search filtering

- **One Vertex AI Search data store** (`DATA_STORE_ID`) indexes all documents (Procedure, Guidelines, and optionally others).
- There is **no server-side filter** by document type. Every search runs over the full store.
- **Document type** is inferred **after** the search using **URI and title**:
  - `config/settings.py` defines `DOC_TYPE_KEYWORDS`:
    - **Procedure:** `procedure`, `assessment`, `process`, `manual`, `instruction`, `operating`, `methodology`
    - **Guidelines:** `guideline`, `guidance`, `policy`, `standard`, `framework`, `criteria`, `rule`
  - Each result is labeled `Procedure`, `Guidelines`, or `Unknown` by matching these keywords against the document URI and title.

### Tool behaviour

| Tool | Behaviour | Flexibility |
|------|-----------|-------------|
| `search_rag(query, num_results)` | Searches the whole store, returns all result types. | Max flexibility; no filtering. |
| `tool_search_procedure(query, num_results)` | Calls `search_rag(query, num_results * 2)`, then keeps only `doc_type == "Procedure"`. If that yields 0 results, **returns all results** (fallback). | Flexible: if URIs/titles don’t match keywords, you still get RAG content. |
| `tool_search_guidelines(query, num_results)` | Same pattern for `doc_type == "Guidelines"`. | Same fallback. |

So: **RAG info is always available**; procedure/guideline “filtering” is best-effort and falls back to unfiltered results when the filter would return nothing.

---

## 2. Using RAG for Teaser Assessment (Procedure + Guidelines)

### Process Analyst (assessment approach & origination method)

- **Role:** Decide assessment approach and origination method for the teaser using the **Procedure** document.
- **RAG usage:**
  - The agent (or tool loop) calls **`search_procedure`** with **free-form queries** (e.g. “proportionality approach thresholds”, “origination methods”, “deal size threshold full assessment”).
  - Queries are **not hardcoded** in logic: they come from the **model** (native function calling or text-based `<TOOL>search_procedure: "..."</TOOL>`).
- **Flexibility from governance:**
  - **Search vocabulary:** `governance_context["search_vocabulary"]` is injected into the Process Analyst instruction (and into Gemini tool descriptions in `function_declarations.py`). So **recommended search terms** are **document-driven** (from governance discovery), not fixed in code.
  - **Instruction text** also includes governance-derived:
    - `requirement_categories`
    - `risk_taxonomy`
    - `asset_class_hints`
    - `extraction_sections`
  - If governance context is missing, **sensible default phrases** are used (e.g. “Assessment approach decision criteria and thresholds”, “Origination methods and their requirements”).
- **Flow:** Teaser text + RAG results (procedure excerpts) → LLM → structured decision (assessment approach, origination method, reasoning, procedure sections cited). So **assessment is explicitly based on procedure content** retrieved via RAG.

### Compliance Advisor (guidelines check)

- **Role:** Assess the deal against **Guidelines** (limits, criteria, policy).
- **RAG usage:**
  - The agent calls **`search_guidelines`** (and optionally **`search_procedure`**) with its own queries.
  - Again, **queries are model-chosen**; tool descriptions can be guided by **governance** (`search_examples` from governance in Compliance Advisor).
- **Flexibility:** Same idea: governance discovery fills `search_vocabulary` and related context so that **which guidelines to search for** adapts to the actual Guidelines document.

### Writer (sections and citations)

- **RAG:** Writer can call **`search_procedure`** (e.g. for required sections and structure) via `_search_procedure_for_sections`, using queries like “required sections for {origination_method}” and “section requirements {assessment_approach}”.
- So **section structure and wording** are also driven by procedure content retrieved via RAG.

---

## 3. Governance Discovery: Making RAG “Document-Driven”

Before agents run, **governance discovery** makes RAG usage **flexible across different Procedure/Guidelines documents**:

1. **Broad RAG queries** (fixed in code but generic):
   - **Procedure:** e.g. “information requirements assessment methods origination”, “required sections content structure output document”, “assessment approach types available decision criteria”, etc.
   - **Guidelines:** e.g. “compliance criteria categories requirements”, “financial ratio requirements thresholds limits covenants”, etc.
2. **Excerpts** from Procedure and Guidelines are collected.
3. An **LLM** extracts from those excerpts:
   - **search_vocabulary** — terms/phrases useful for future RAG queries (injected into Process Analyst and Compliance Advisor prompts and tool descriptions).
   - **terminology_map** — domain terms and synonyms (used for **semantic matching** in requirement extraction).
   - **requirement_categories**, **section_templates**, **risk_taxonomy**, **deal_taxonomy**, **compliance_framework**, etc.

So: **the same codebase** can work with different Procedure/Guidelines documents; **what to search for** and **how to talk about it** come from the documents themselves via RAG + discovery.

---

## 4. Semantic Matching (Teaser ↔ Procedures / Requirements)

- **Requirement discovery** (which fields are needed) is driven by **Procedure** via RAG and governance (e.g. `requirement_categories`, section templates).
- **Filling** those requirements from the **teaser** (and analysis) uses **semantic matching** so that different wording still matches:
  - In the **legacy phase-based UI** (`ui/legacy/phases/process_gaps.py`), the extraction prompt includes **`get_terminology_synonyms(governance_context)`**, which turns `terminology_map` into “equivalent terms” instructions (e.g. “Track Record” = “Experience”). So the LLM is told to **search for concepts, not exact words** when pulling values from the teaser.
  - **Governance discovery** provides `terminology_map` from the actual documents; there are **no hardcoded domain synonyms** in the discovery module.
- In the **conversational flow**, requirements are **discovered** (list + some pre-filled from analysis); the **same semantic-matching idea** could be applied when adding a “fill from teaser” step that uses governance synonyms.

So: **flexibility for assessment** comes from (1) RAG over Procedure/Guidelines, (2) governance-derived search vocabulary and terminology, and (3) semantic matching for mapping teaser wording to required fields.

---

## 5. Summary Table

| Aspect | Implementation | Flexibility |
|--------|----------------|-------------|
| **Where RAG runs** | Single Vertex AI Search data store | Add new doc types by extending `DOC_TYPE_KEYWORDS` and optional filters. |
| **Procedure vs Guidelines** | Post-search filter by URI/title keywords; fallback to all results | Works even when filenames/URIs don’t match; no API-level separation of stores. |
| **What gets searched** | Agent (or tool loop) chooses queries; tool descriptions can use governance `search_vocabulary` | Document-driven: different Procedure/Guidelines → different suggested queries. |
| **Teaser assessment** | Process Analyst uses RAG (procedure) to decide approach/method; Compliance uses RAG (guidelines) for checks | Assessment is explicitly based on procedure and guideline content retrieved via RAG. |
| **Synonyms / terminology** | `terminology_map` from governance discovery; used in legacy extraction prompt | Semantic matching for “teaser field ↔ requirement” is document-driven, not hardcoded. |
| **Governance discovery queries** | Fixed list of broad PROCEDURE_QUERIES and GUIDELINES_QUERIES | Broad enough for many institutions; could be made configurable later. |

---

## 6. Possible Improvements

- **Configurable discovery queries:** Allow deployment-specific PROCEDURE_QUERIES / GUIDELINES_QUERIES (e.g. from config or env) so new institutions don’t depend on the default list alone.
- **Server-side document type filter:** If Vertex AI Search supports filter by metadata or document ID, using it could reduce irrelevant results when the store contains many doc types.
- **Semantic matching in conversational flow:** Ensure any “fill requirements from teaser” step in the chat path also receives `get_terminology_synonyms(governance_context)` (or equivalent) so terminology flexibility is consistent with the legacy UI.

---

*This note complements the architecture and audit docs; it focuses only on RAG and the flexibility of using RAG info for teaser assessment based on procedures and guidelines.*
