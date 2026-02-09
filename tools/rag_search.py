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


def _get_serving_config() -> str:
    """Get the serving config path for search."""
    return (
        f"projects/{PROJECT_ID}/locations/{SEARCH_LOCATION}/"
        f"collections/default_collection/dataStores/{DATA_STORE_ID}/"
        f"servingConfigs/default_search"
    )


def _convert_proto_to_dict(obj) -> Any:
    """Convert protobuf/MapComposite objects to Python native types."""
    if obj is None:
        return None
    
    if isinstance(obj, (str, int, float, bool)):
        return obj
    
    if isinstance(obj, (list, tuple)):
        return [_convert_proto_to_dict(item) for item in obj]
    
    if isinstance(obj, dict):
        return {k: _convert_proto_to_dict(v) for k, v in obj.items()}
    
    # Try dict-like conversion
    try:
        if hasattr(obj, 'items'):
            return {k: _convert_proto_to_dict(v) for k, v in obj.items()}
    except Exception as e:
        logger.debug("Proto dict-like conversion failed: %s", e)

    # Try list-like conversion
    try:
        if hasattr(obj, '__iter__') and not isinstance(obj, str):
            return [_convert_proto_to_dict(item) for item in obj]
    except Exception as e:
        logger.debug("Proto list-like conversion failed: %s", e)

    # Try protobuf conversion
    try:
        from google.protobuf.json_format import MessageToDict
        if hasattr(obj, 'pb'):
            return MessageToDict(obj.pb)
        return MessageToDict(obj)
    except Exception as e:
        logger.debug("Proto MessageToDict conversion failed: %s", e)
    
    return str(obj)


def _extract_text_from_field(field_data) -> str:
    """Extract text content from various field formats."""
    if not field_data:
        return ""
    
    data = _convert_proto_to_dict(field_data)
    
    if isinstance(data, str):
        return data
    
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
        texts = [_extract_text_from_field(item) for item in data]
        return "\n".join([t for t in texts if t])
    
    return str(data) if data else ""


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
        # Create client
        opts = None
        if SEARCH_LOCATION != "global":
            opts = ClientOptions(api_endpoint=f"{SEARCH_LOCATION}-discoveryengine.googleapis.com")
        
        client = discoveryengine.SearchServiceClient(
            credentials=get_credentials(),
            client_options=opts
        )
        
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
        
        # Execute search
        response = client.search(request)
        
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
            
            # Collect content
            content_parts = []
            
            # Extractive answers
            if "extractive_answers" in data:
                for ans in data["extractive_answers"]:
                    text = _extract_text_from_field(ans)
                    if text and len(text) > 10:
                        content_parts.append(text)
            
            # Extractive segments
            if "extractive_segments" in data:
                for seg in data["extractive_segments"]:
                    text = _extract_text_from_field(seg)
                    if text and len(text) > 10:
                        content_parts.append(text)
            
            # Snippets
            if "snippets" in data:
                for snip in data["snippets"]:
                    text = _extract_text_from_field(snip)
                    if text and len(text) > 10:
                        content_parts.append(text)
            
            # Deduplicate
            unique_parts = []
            for part in content_parts:
                is_dup = any(part in existing or existing in part for existing in unique_parts)
                if not is_dup:
                    unique_parts.append(part)
            
            content = "\n\n".join(unique_parts[:5])
            
            results.append({
                "id": doc.id,
                "uri": uri,
                "doc_type": doc_type,
                "title": title,
                "content": content[:4000]
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
