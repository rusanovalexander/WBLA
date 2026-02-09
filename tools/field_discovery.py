"""
Dynamic Field Discovery for Credit Pack v3

Analyzes deal characteristics and Procedure to determine which fields
should be extracted, rather than using hardcoded schemas.
"""

from typing import Dict, List, Any


def discover_required_fields_prompt(teaser_text: str, deal_characteristics: Dict) -> str:
    """
    Generate prompt for discovering required fields based on deal type.
    
    Args:
        teaser_text: The deal teaser content
        deal_characteristics: Dict with transaction_type, structure, asset_class, etc.
    
    Returns:
        Prompt for LLM to discover required fields
    """
    
    chars = deal_characteristics
    
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

Based on this deal type and the Procedure requirements, list ALL information fields that need to be extracted.

### Core Categories (always include):
1. **DEAL INFORMATION** - Basic transaction details
2. **BORROWER** - Entity information
3. **FINANCIALS** - Key metrics

### Conditional Categories (include if applicable):
4. **SPONSOR** - If sponsor-backed transaction
5. **GUARANTOR** - If guarantees mentioned
6. **ASSET** - If asset/collateral-based
7. **SECURITY** - If secured transaction
8. **CONSTRUCTION** - If construction/development deal
9. **ACQUISITION** - If acquisition financing
10. **REFINANCING** - If refinancing transaction

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
      }},
      {{
        "name": "Facility Tenor",
        "description": "Loan maturity period",
        "why_required": "Required for risk assessment",
        "data_type": "duration",
        "typical_source": "teaser",
        "priority": "CRITICAL"
      }}
    ]
  }},
  {{
    "category": "SECURITY",
    "fields": [
      {{
        "name": "Security Type",
        "description": "Type of security (mortgage, pledge, etc.)",
        "why_required": "Required for secured transaction compliance",
        "data_type": "text",
        "typical_source": "teaser",
        "priority": "CRITICAL"
      }}
    ]
  }}
]
```

**Rules:**
1. Only include categories that apply to THIS deal
2. For each field, specify WHY it's required (cite Procedure if possible)
3. Mark priority: CRITICAL, IMPORTANT, or SUPPORTING
4. If deal is unsecured, do NOT include SECURITY category
5. If no construction, do NOT include CONSTRUCTION category
6. If no guarantor mentioned, do NOT include GUARANTOR category

Return ONLY the JSON array.
"""
    
    return prompt


def analyze_deal_characteristics_prompt(teaser_text: str) -> str:
    """
    Generate prompt to analyze deal characteristics before field discovery.
    """
    
    prompt = f"""Analyze this teaser and identify the key characteristics of this deal.

## TEASER

{teaser_text}

## YOUR TASK

Identify the following characteristics:

**Output as JSON:**

```json
{{
  "transaction_type": "new | modification | renewal | refinancing | acquisition",
  "structure": "secured | unsecured | mezzanine | hybrid",
  "asset_class": "real_estate | corporate | project_finance | trade_finance | other",
  "asset_subtype": "office | retail | residential | industrial | hotel | mixed | N/A",
  "special_features": ["construction", "development", "sale_leaseback", "acquisition"],
  "parties": ["borrower", "sponsor", "guarantor", "servicer"],
  "jurisdiction": "Netherlands | Germany | UK | etc.",
  "regulatory_context": "standard | real_estate_specific | project_finance_specific",
  "complexity_indicators": ["multi_asset", "multi_jurisdiction", "subordinated", "complex_structure"]
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
    "value": "EUR 75,000,000",
    "source_quote": "The facility amount is EUR 75 million...",
    "confidence": "HIGH"
  }},
  {{
    "id": 2,
    "name": "Facility Tenor",
    "value": "NOT STATED IN TEASER",
    "source_quote": "",
    "confidence": "N/A"
  }}
]
```

Return ONLY the JSON array. Include ALL {len(schema)} fields in your response.
"""
    
    return prompt
