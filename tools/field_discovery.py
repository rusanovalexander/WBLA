"""
Dynamic Field Discovery for Credit Pack v3 — DOCUMENT-DRIVEN VERSION

Key changes:
- discover_required_fields_prompt() accepts governance_context parameter
- analyze_deal_characteristics_prompt() accepts governance_context parameter
- Categories and taxonomy derived from governance documents when available
- Falls back to sensible defaults when governance context is not available
"""

from __future__ import annotations
from typing import Dict, List, Any


def discover_required_fields_prompt(
    teaser_text: str,
    deal_characteristics: Dict,
    governance_context: dict[str, Any] | None = None,
) -> str:
    """
    Generate prompt for discovering required fields based on deal type.

    Args:
        teaser_text: The deal teaser content
        deal_characteristics: Dict with transaction_type, structure, asset_class, etc.
        governance_context: Optional governance context from discovery

    Returns:
        Prompt for LLM to discover required fields
    """

    chars = deal_characteristics

    # Build categories from governance context or defaults (M10)
    if governance_context and governance_context.get("requirement_categories"):
        cats = governance_context["requirement_categories"]
        core_cats = cats[:3] if len(cats) >= 3 else cats
        conditional_cats = cats[3:] if len(cats) > 3 else []

        core_section = "### Core Categories (always include):\n"
        for i, cat in enumerate(core_cats, start=1):
            core_section += f"{i}. **{cat.upper()}** - {cat} details\n"

        if conditional_cats:
            cond_section = "\n### Conditional Categories (include if applicable):\n"
            for i, cat in enumerate(conditional_cats, start=len(core_cats) + 1):
                cond_section += f"{i}. **{cat.upper()}** - If relevant to this deal\n"
        else:
            cond_section = ""
    else:
        core_section = (
            "### Core Categories:\n"
            "Determine the appropriate information categories based on the deal characteristics above.\n"
            "Typical categories include deal details, entity information, financial metrics, etc.\n"
            "but you MUST adapt to what THIS specific deal requires.\n"
        )
        cond_section = (
            "\n### Additional Categories:\n"
            "Include any additional categories that the deal characteristics suggest are relevant.\n"
            "Do not use a predetermined list — derive categories from the deal context.\n"
        )

    prompt = f"""Analyze this deal and determine which information fields need to be extracted.

## DEAL CHARACTERISTICS

**Transaction Type:** {chars.get('transaction_type', 'Unknown')}
**Structure:** {chars.get('structure', 'Unknown')}
**Asset Class:** {chars.get('asset_class', 'N/A')}
**Special Features:** {chars.get('special_features', 'None')}
**Parties Involved:** {', '.join(chars.get('parties', []))}
**Jurisdiction:** {chars.get('jurisdiction', 'Unknown')}

## TEASER EXCERPT
{teaser_text[:2000]}

## YOUR TASK

Based on this deal type and the governance requirements, list ALL information fields that need to be extracted.

{core_section}{cond_section}

## OUTPUT FORMAT

Return a JSON array of field groups:

```json
[
  {{
    "category": "DEAL",
    "fields": [
      {{
        "name": "Facility Amount",
        "description": "Total facility with currency",
        "why_required": "Core parameter for credit assessment",
        "data_type": "currency",
        "typical_source": "teaser",
        "priority": "CRITICAL"
      }}
    ]
  }}
]
```

**Rules:**
1. Only include categories that apply to THIS deal
2. For each field, specify WHY it's required (cite governance documents if possible)
3. Mark priority: CRITICAL, IMPORTANT, or SUPPORTING
4. Only include conditional categories if the deal characteristics warrant them

Return ONLY the JSON array.
"""

    return prompt


def analyze_deal_characteristics_prompt(
    teaser_text: str,
    governance_context: dict[str, Any] | None = None,
) -> str:
    """
    Generate prompt to analyze deal characteristics before field discovery.

    Args:
        teaser_text: The deal teaser content
        governance_context: Optional governance context from discovery
    """

    # Build taxonomy from governance context or defaults (M11)
    if governance_context and governance_context.get("deal_taxonomy"):
        taxonomy = governance_context["deal_taxonomy"]
        taxonomy_lines = []
        for dim, values in taxonomy.items():
            dim_label = dim.replace("_", " ").title()
            if isinstance(values, list) and values:
                val_str = " | ".join(str(v) for v in values)
                taxonomy_lines.append(f'  "{dim}": "{val_str}"')
            else:
                taxonomy_lines.append(f'  "{dim}": "<as identified>"')
        taxonomy_json = ",\n".join(taxonomy_lines)
    else:
        taxonomy_json = (
            '  "transaction_type": "<as identified from teaser>",\n'
            '  "structure": "<as identified from teaser>",\n'
            '  "parties": ["<as identified from teaser>"],\n'
            '  "jurisdiction": "<as identified from teaser>"\n'
            '  // Add any other classification dimensions relevant to this specific deal'
        )

    prompt = f"""Analyze this teaser and identify the key characteristics of this deal.

## TEASER

{teaser_text}

## YOUR TASK

Identify the following characteristics:

**Output as JSON:**

```json
{{
{taxonomy_json}
}}
```

Analyze carefully and only include elements that are explicitly mentioned or clearly implied.

Return ONLY the JSON object.
"""

    return prompt


def create_extraction_schema_from_fields(field_groups: List[Dict]) -> List[Dict]:
    """
    Convert discovered fields into extraction schema format.

    Args:
        field_groups: List of category/fields dicts from LLM

    Returns:
        Flat list of fields with metadata for extraction
    """

    extraction_schema = []
    field_id = 1

    for group in field_groups:
        category = group.get("category", "UNKNOWN")
        fields = group.get("fields", [])

        for field in fields:
            extraction_schema.append({
                "id": field_id,
                "category": category,
                "name": field.get("name", "Unknown Field"),
                "description": field.get("description", ""),
                "why_required": field.get("why_required", ""),
                "data_type": field.get("data_type", "text"),
                "typical_source": field.get("typical_source", "teaser"),
                "priority": field.get("priority", "IMPORTANT"),
                "value": "",
                "source_quote": "",
                "confidence": "N/A",
                "status": "pending"
            })
            field_id += 1

    return extraction_schema


def generate_dynamic_extraction_prompt(schema: List[Dict], teaser_text: str) -> str:
    """
    Generate extraction prompt using discovered schema.

    Args:
        schema: Extraction schema from create_extraction_schema_from_fields
        teaser_text: Teaser to extract from

    Returns:
        Prompt for extraction with discovered fields
    """

    # Group by category
    categories = {}
    for field in schema:
        cat = field["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(field)

    # Build field descriptions
    field_descriptions = ""
    for category, fields in categories.items():
        field_descriptions += f"\n**{category}** ({len(fields)} fields):\n"
        for f in fields:
            priority_marker = "🔴" if f["priority"] == "CRITICAL" else ("🟡" if f["priority"] == "IMPORTANT" else "🟢")
            field_descriptions += f"- {priority_marker} **{f['name']}**: {f['description']}\n"

    prompt = f"""Extract ALL available data from this teaser using the customized field schema.

## TEASER DOCUMENT

{teaser_text}

## FIELDS TO EXTRACT
{field_descriptions}

## EXTRACTION RULES

1. Extract ONLY what is explicitly stated in the teaser
2. If a value is not stated, write "NOT STATED IN TEASER"
3. Quote the exact source text as evidence
4. Assign Confidence: HIGH (explicit), MEDIUM (inferred), LOW (uncertain), N/A (not stated)

## OUTPUT FORMAT

Return a JSON array with all fields:

```json
[
  {{
    "id": 1,
    "name": "Facility Amount",
    "value": "[amount in deal currency]",
    "source_quote": "exact quote from the teaser...",
    "confidence": "HIGH"
  }}
]
```

Return ONLY the JSON array. Include ALL {len(schema)} fields in your response.
"""

    return prompt
