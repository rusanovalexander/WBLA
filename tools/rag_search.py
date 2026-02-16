"""
RAG Search Tool - Vertex AI Search (Discovery Engine)

Searches indexed Procedure and Guidelines documents.
"""

from pathlib import Path
from typing import Dict, Any, List
import logging
import re


from config.settings import PROJECT_ID, SEARCH_LOCATION, DATA_STORE_ID, DOC_TYPE_KEYWORDS, get_credentials

logger = logging.getLogger(__name__)

# Cached Discovery Engine client (avoid re-creating per search call)
_search_client_cache: dict[str, Any] = {}


def _get_serving_config() -> str:
    """Get the serving config path for search."""
    return (
        f"projects/{PROJECT_ID}/locations/{SEARCH_LOCATION}/"
        f"collections/default_collection/dataStores/{DATA_STORE_ID}/"
        f"servingConfigs/default_search"
    )


def _convert_proto_to_dict(obj, max_depth: int = 20, _current_depth: int = 0) -> Any:
    """
    Convert protobuf/MapComposite objects to Python native types.

    Handles Discovery Engine's protobuf wrapper objects (MapComposite,
    RepeatedComposite) which can cause infinite recursion if traversed
    via generic hasattr('items')/hasattr('__iter__') checks.

    Strategy:
    1. Try protobuf MessageToDict FIRST (atomic, no recursion needed)
    2. Convert MapComposite/RepeatedComposite to native dict/list FIRST,
       then recurse on the native types only
    3. Fall back to str() for anything unrecognizable

    Args:
        obj: Object to convert
        max_depth: Maximum recursion depth (default 20)
        _current_depth: Current recursion depth (internal)
    """
    # Hard depth limit — return string representation
    if _current_depth >= max_depth:
        try:
            return str(obj)[:500]
        except Exception:
            return "[MAX_DEPTH_REACHED]"

    if obj is None:
        return None

    # Primitives — no recursion needed
    if isinstance(obj, (str, int, float, bool)):
        return obj

    # Native Python dict — safe to recurse
    if isinstance(obj, dict):
        return {
            str(k): _convert_proto_to_dict(v, max_depth, _current_depth + 1)
            for k, v in obj.items()
        }

    # Native Python list/tuple — safe to recurse
    if isinstance(obj, (list, tuple)):
        return [
            _convert_proto_to_dict(item, max_depth, _current_depth + 1)
            for item in obj
        ]

    # --- Non-native types below: protobuf wrappers, MapComposite, etc. ---

    # 1. Try protobuf MessageToDict FIRST — handles the entire tree atomically
    try:
        from google.protobuf.json_format import MessageToDict
        if hasattr(obj, 'pb'):
            return MessageToDict(obj.pb)
        if hasattr(obj, 'DESCRIPTOR'):
            return MessageToDict(obj)
    except Exception:
        pass

    # 2. Detect MapComposite / RepeatedComposite by type name
    #    (avoids relying on hasattr('items') which matches too broadly)
    type_name = type(obj).__name__

    if 'MapComposite' in type_name or 'MessageMapContainer' in type_name:
        try:
            native_dict = dict(obj)
            return {
                str(k): _convert_proto_to_dict(v, max_depth, _current_depth + 1)
                for k, v in native_dict.items()
            }
        except (TypeError, ValueError, RecursionError) as e:
            logger.debug("MapComposite dict conversion failed: %s", e)

    if 'RepeatedComposite' in type_name or 'Repeated' in type_name:
        try:
            native_list = list(obj)
            return [
                _convert_proto_to_dict(item, max_depth, _current_depth + 1)
                for item in native_list
            ]
        except (TypeError, ValueError, RecursionError) as e:
            logger.debug("RepeatedComposite list conversion failed: %s", e)

    # 3. Safe dict-like fallback: only if type has 'items' AND is NOT a protobuf
    #    message (which also has 'items' but leads to recursion)
    if hasattr(obj, 'items') and not hasattr(obj, 'DESCRIPTOR') and 'Proto' not in type_name:
        try:
            native_dict = dict(obj)  # Convert to native dict FIRST
            return {
                str(k): _convert_proto_to_dict(v, max_depth, _current_depth + 1)
                for k, v in native_dict.items()
            }
        except (TypeError, ValueError, RecursionError) as e:
            logger.debug("Dict-like conversion failed for %s: %s", type_name, e)

    # 4. Last resort — string representation (truncated)
    try:
        return str(obj)[:500]
    except Exception:
        return "[UNCONVERTIBLE]"


def _extract_text_from_field(field_data, _depth: int = 0) -> str:
    """Extract text content from various field formats.

    Args:
        field_data: Raw field data (may be protobuf, dict, str, list)
        _depth: Internal recursion guard (max 5 levels for list unpacking)
    """
    if not field_data:
        return ""

    # Guard against deep recursion in nested lists
    if _depth > 5:
        return str(field_data)[:200] if field_data else ""

    data = _convert_proto_to_dict(field_data)

    if isinstance(data, str):
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', data)
        return text.strip()

    if isinstance(data, dict):
        for key in ['content', 'text', 'snippet', 'answer', 'segment', 'value']:
            if key in data and data[key]:
                text = data[key]
                if isinstance(text, str):
                    # Remove HTML tags
                    text = re.sub(r'<[^>]+>', '', text)
                    return text.strip()

        # Get any long string value
        for v in data.values():
            if isinstance(v, str) and len(v) > 20:
                return v.strip()

    if isinstance(data, list):
        texts = [_extract_text_from_field(item, _depth + 1) for item in data[:10]]
        return "\n".join([t for t in texts if t])

    return str(data)[:500] if data else ""


def search_rag(query: str, num_results: int = 5) -> Dict[str, Any]:
    """
    Search Vertex AI Search for relevant documents.
    
    Args:
        query: Search query
        num_results: Maximum results to return
        
    Returns:
        Dict with status, results, and any errors
    """
    
    if not DATA_STORE_ID:
        return {
            "status": "ERROR",
            "query": query,
            "results": [],
            "error": "DATA_STORE_ID not configured. Set it in config/settings.py"
        }
    
    try:
        from google.cloud import discoveryengine_v1 as discoveryengine
        from google.api_core.client_options import ClientOptions
    except ImportError:
        return {
            "status": "ERROR",
            "query": query,
            "results": [],
            "error": "google-cloud-discoveryengine not installed"
        }
    
    try:
        # Reuse cached client (avoids gRPC channel setup on every call)
        cache_key = f"{PROJECT_ID}_{SEARCH_LOCATION}_{DATA_STORE_ID}"
        if cache_key in _search_client_cache:
            client = _search_client_cache[cache_key]
        else:
            opts = None
            if SEARCH_LOCATION != "global":
                opts = ClientOptions(api_endpoint=f"{SEARCH_LOCATION}-discoveryengine.googleapis.com")
            client = discoveryengine.SearchServiceClient(
                credentials=get_credentials(),
                client_options=opts
            )
            _search_client_cache[cache_key] = client
        
        serving_config = _get_serving_config()
        
        # Build request
        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=query,
            page_size=num_results,
            content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                    return_snippet=True,
                    max_snippet_count=5
                ),
                extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                    max_extractive_answer_count=3,
                    max_extractive_segment_count=5
                )
            )
        )
        
        # Execute search (with 30s timeout to prevent UI freeze)
        response = client.search(request, timeout=30.0)
        
        # Parse results
        results = []
        for result in response.results:
            doc = result.document
            
            raw_data = dict(doc.derived_struct_data) if doc.derived_struct_data else {}
            data = _convert_proto_to_dict(raw_data)
            
            # Get URI
            uri = data.get("link", data.get("uri", ""))

            # Get title early — needed for doc type detection (DD-4)
            title = data.get("title", "")
            if not title and uri:
                title = Path(uri).stem.replace("-", " ").replace("_", " ")
            if not title:
                title = doc.id

            # Determine document type — check both URI and title for keywords
            doc_type = "Unknown"
            uri_lower = uri.lower() if uri else ""
            title_lower = title.lower() if title else ""
            # Check URI first (most reliable), then title as fallback
            # Uses configurable DOC_TYPE_KEYWORDS from settings.py
            for dtype, keywords in DOC_TYPE_KEYWORDS.items():
                if any(w in uri_lower for w in keywords):
                    doc_type = dtype
                    break
            if doc_type == "Unknown":
                for dtype, keywords in DOC_TYPE_KEYWORDS.items():
                    if any(w in title_lower for w in keywords):
                        doc_type = dtype
                        break
            
            # Collect content and page numbers
            content_parts = []
            page_numbers = set()  # Collect unique page numbers

            # Extractive answers (with page numbers)
            if "extractive_answers" in data:
                for ans in data["extractive_answers"]:
                    ans_dict = _convert_proto_to_dict(ans) if not isinstance(ans, dict) else ans
                    text = _extract_text_from_field(ans)
                    if text and len(text) > 10:
                        content_parts.append(text)
                    # Extract page number if available
                    if isinstance(ans_dict, dict) and "pageNumber" in ans_dict:
                        page_numbers.add(str(ans_dict["pageNumber"]))

            # Extractive segments (with page numbers)
            if "extractive_segments" in data:
                for seg in data["extractive_segments"]:
                    seg_dict = _convert_proto_to_dict(seg) if not isinstance(seg, dict) else seg
                    text = _extract_text_from_field(seg)
                    if text and len(text) > 10:
                        content_parts.append(text)
                    # Extract page number if available
                    if isinstance(seg_dict, dict) and "pageNumber" in seg_dict:
                        page_numbers.add(str(seg_dict["pageNumber"]))

            # Snippets (usually don't have page numbers, but check anyway)
            if "snippets" in data:
                for snip in data["snippets"]:
                    snip_dict = _convert_proto_to_dict(snip) if not isinstance(snip, dict) else snip
                    text = _extract_text_from_field(snip)
                    if text and len(text) > 10:
                        content_parts.append(text)
                    # Extract page number if available
                    if isinstance(snip_dict, dict) and "pageNumber" in snip_dict:
                        page_numbers.add(str(snip_dict["pageNumber"]))

            # Deduplicate
            unique_parts = []
            for part in content_parts:
                is_dup = any(part in existing or existing in part for existing in unique_parts)
                if not is_dup:
                    unique_parts.append(part)

            content = "\n\n".join(unique_parts[:5])

            # Build page reference string
            page_ref = ""
            if page_numbers:
                sorted_pages = sorted(page_numbers, key=lambda x: int(x) if x.isdigit() else 999)
                if len(sorted_pages) == 1:
                    page_ref = f"p.{sorted_pages[0]}"
                elif len(sorted_pages) <= 3:
                    page_ref = f"pp.{', '.join(sorted_pages)}"
                else:
                    page_ref = f"pp.{sorted_pages[0]}-{sorted_pages[-1]}"

            results.append({
                "id": doc.id,
                "uri": uri,
                "doc_type": doc_type,
                "title": title,
                "content": content[:4000],
                "page_reference": page_ref  # NEW: page reference for citations
            })
        
        return {
            "status": "OK",
            "query": query,
            "num_results": len(results),
            "results": results
        }
        
    except Exception as e:
        import traceback
        return {
            "status": "ERROR",
            "query": query,
            "results": [],
            "error": str(e),
            "traceback": traceback.format_exc()
        }


# =============================================================================
# Tool Wrappers
# =============================================================================

def tool_search_rag(query: str, num_results: int = 5) -> Dict[str, Any]:
    """Search RAG for any query."""
    return search_rag(query, num_results)


def tool_search_procedure(query: str, num_results: int = 5) -> Dict[str, Any]:
    """Search and filter for Procedure documents only. Falls back to all results if filtering yields 0."""
    result = search_rag(query, num_results * 2)

    if result["status"] != "OK":
        return result

    filtered = [r for r in result["results"] if r["doc_type"] == "Procedure"]

    # Fallback: if URI-based filtering returned 0 results, return all results
    # (the URI may not contain 'procedure' keyword)
    if not filtered and result["results"]:
        logger.info("Procedure filter returned 0 results for '%s', falling back to all %d results",
                     query, len(result["results"]))
        filtered = result["results"]

    return {
        "status": "OK",
        "query": query,
        "num_results": len(filtered),
        "results": filtered[:num_results]
    }


def tool_search_guidelines(query: str, num_results: int = 5) -> Dict[str, Any]:
    """Search and filter for Guidelines documents only. Falls back to all results if filtering yields 0."""
    result = search_rag(query, num_results * 2)

    if result["status"] != "OK":
        return result

    filtered = [r for r in result["results"] if r["doc_type"] == "Guidelines"]

    # Fallback: if URI-based filtering returned 0 results, return all results
    if not filtered and result["results"]:
        logger.info("Guidelines filter returned 0 results for '%s', falling back to all %d results",
                     query, len(result["results"]))
        filtered = result["results"]

    return {
        "status": "OK",
        "query": query,
        "num_results": len(filtered),
        "results": filtered[:num_results]
    }


def test_rag_connection() -> Dict[str, Any]:
    """Test RAG connection with a simple query."""
    result = search_rag("credit", 1)
    
    if result["status"] != "OK":
        return {
            "connected": False,
            "error": result.get("error", "Unknown error"),
            "data_store": DATA_STORE_ID
        }
    
    return {
        "connected": True,
        "data_store": DATA_STORE_ID,
        "num_results": result["num_results"],
        "sample_doc": result["results"][0]["title"] if result["results"] else None
    }


# =============================================================================
# Example Credit Pack Search (Local File Search)
# =============================================================================

def tool_search_examples(
    query: str,
    num_results: int = 3,
    examples_folder: str = None
) -> dict[str, Any]:
    """
    Search example credit pack files in data/examples folder.

    This does NOT use Vertex AI Search - it's a local file search.

    Args:
        query: Search query (e.g., "commercial real estate", "infrastructure")
        num_results: Max number of examples to return
        examples_folder: Path to examples folder (defaults to data/examples)

    Returns:
        {
            "status": "OK" | "ERROR",
            "num_results": int,
            "results": [
                {
                    "filename": str,
                    "title": str,  # Extracted from filename
                    "sector": str,  # Guessed from filename/content
                    "content_preview": str,  # First 500 chars
                    "relevance_score": float,  # Simple keyword matching score
                },
                ...
            ],
            "query": str
        }
    """

    if examples_folder is None:
        from config.settings import EXAMPLES_FOLDER
        examples_folder = EXAMPLES_FOLDER

    examples_path = Path(examples_folder)

    if not examples_path.exists():
        logger.warning(f"Examples folder not found: {examples_folder}")
        return {
            "status": "ERROR",
            "error": f"Examples folder not found: {examples_folder}",
            "num_results": 0,
            "results": [],
            "query": query
        }

    # Find all document files in examples folder
    doc_extensions = [".pdf", ".docx", ".txt", ".md"]
    example_files = []

    for ext in doc_extensions:
        example_files.extend(examples_path.glob(f"**/*{ext}"))

    if not example_files:
        logger.info(f"No example files found in {examples_folder}")
        return {
            "status": "OK",
            "num_results": 0,
            "results": [],
            "query": query,
            "message": "No example credit packs found in database"
        }

    # Score each file based on query relevance
    scored_examples = []
    query_lower = query.lower()
    query_terms = set(query_lower.split())

    for file_path in example_files:
        filename = file_path.name
        filename_lower = filename.lower()

        # Calculate simple relevance score (keyword matching)
        score = 0.0

        # Full query match in filename
        if query_lower in filename_lower:
            score += 10.0

        # Individual term matches
        for term in query_terms:
            if term in filename_lower:
                score += 2.0

        # Sector keywords
        sector_keywords = {
            "infrastructure": ["infrastructure", "transport", "road", "bridge", "port"],
            "real_estate": ["real estate", "property", "commercial", "residential", "office"],
            "energy": ["energy", "power", "renewable", "solar", "wind"],
            "financial": ["financial", "bank", "finance", "loan"],
            "industrial": ["industrial", "manufacturing", "factory"],
        }

        detected_sector = "general"
        for sector, keywords in sector_keywords.items():
            if any(kw in filename_lower for kw in keywords):
                detected_sector = sector
                # Boost score if query matches sector
                if any(kw in query_lower for kw in keywords):
                    score += 5.0
                break

        # Try to load content preview (first 500 chars)
        content_preview = ""
        try:
            if file_path.suffix == ".txt" or file_path.suffix == ".md":
                content_preview = file_path.read_text(encoding="utf-8")[:500]
                # Boost score if query terms appear in content
                content_lower = content_preview.lower()
                for term in query_terms:
                    if term in content_lower:
                        score += 1.0
        except Exception as e:
            logger.debug(f"Could not read {filename}: {e}")

        # Extract title from filename (remove extension, replace underscores/hyphens)
        title = file_path.stem.replace("_", " ").replace("-", " ").title()

        scored_examples.append({
            "filename": filename,
            "file_path": str(file_path),
            "title": title,
            "sector": detected_sector,
            "content_preview": content_preview or "[Content preview not available]",
            "relevance_score": score,
        })

    # Sort by relevance score (descending)
    scored_examples.sort(key=lambda x: x["relevance_score"], reverse=True)

    # Return top N results
    top_results = scored_examples[:num_results]

    logger.info(f"Example search: '{query}' found {len(top_results)}/{len(scored_examples)} relevant examples")

    return {
        "status": "OK",
        "num_results": len(top_results),
        "results": top_results,
        "query": query,
        "total_examples": len(scored_examples)
    }


# =============================================================================
# Native Function Calling Aliases (Fix for C2)
# =============================================================================

# Create aliases without "tool_" prefix for Gemini native function calling
# This fixes the name mismatch between function declarations and actual functions
search_procedure = tool_search_procedure
search_guidelines = tool_search_guidelines
search_rag = tool_search_rag
search_examples = tool_search_examples

# Export both naming conventions
__all__ = [
    # Original names (for backward compatibility)
    'tool_search_procedure',
    'tool_search_guidelines',
    'tool_search_rag',
    'tool_search_examples',
    'test_rag_connection',
    # Native calling aliases (for Gemini function declarations)
    'search_procedure',
    'search_guidelines',
    'search_rag',
    'search_examples',
]


# =============================================================================
# Test
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("RAG SEARCH TEST")
    print("=" * 60)
    print(f"Data Store: {DATA_STORE_ID}")
    print(f"Project: {PROJECT_ID}")
    print(f"Location: {SEARCH_LOCATION}")
    
    # Test connection
    print("\n--- Connection Test ---")
    conn = test_rag_connection()
    print(f"Connected: {conn['connected']}")
    if not conn['connected']:
        print(f"Error: {conn.get('error')}")
    else:
        print(f"Sample doc: {conn.get('sample_doc')}")
    
    # Test queries
    test_queries = [
        "credit granting criteria",
        "LTV requirements",
        "creditworthiness assessment"
    ]
    
    for query in test_queries:
        print(f"\n--- Query: '{query}' ---")
        result = tool_search_rag(query, 3)
        print(f"Status: {result['status']}")
        print(f"Results: {result.get('num_results', 0)}")
        
        for i, r in enumerate(result.get("results", []), 1):
            print(f"  {i}. [{r['doc_type']}] {r['title']}")
            if r['content']:
                preview = r['content'][:150].replace('\n', ' ')
                print(f"     {preview}...")
