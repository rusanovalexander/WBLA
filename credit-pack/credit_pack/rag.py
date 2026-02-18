"""
RAG via Vertex AI Search (Discovery Engine). Procedure and Guidelines documents.
"""

import logging
import re
from pathlib import Path
from typing import Any

from . import config

logger = logging.getLogger(__name__)
_search_client_cache: dict[str, Any] = {}


def _get_serving_config() -> str:
    return (
        f"projects/{config.PROJECT_ID}/locations/{config.SEARCH_LOCATION}/"
        f"collections/default_collection/dataStores/{config.DATA_STORE_ID}/"
        f"servingConfigs/default_search"
    )


def _convert_proto_to_dict(obj: Any, max_depth: int = 20, _depth: int = 0) -> Any:
    if _depth >= max_depth:
        return str(obj)[:500] if obj else None
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _convert_proto_to_dict(v, max_depth, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_convert_proto_to_dict(x, max_depth, _depth + 1) for x in obj]
    try:
        from google.protobuf.json_format import MessageToDict
        if hasattr(obj, "pb"):
            return MessageToDict(obj.pb)
        if hasattr(obj, "DESCRIPTOR"):
            return MessageToDict(obj)
    except Exception:
        pass
    t = type(obj).__name__
    if "Map" in t or "Composite" in t:
        try:
            return _convert_proto_to_dict(dict(obj), max_depth, _depth + 1)
        except Exception:
            pass
    if "Repeated" in t:
        try:
            return _convert_proto_to_dict(list(obj), max_depth, _depth + 1)
        except Exception:
            pass
    return str(obj)[:500]


def _safe_struct_to_dict(struct_data: Any) -> dict:
    if not struct_data:
        return {}
    t = type(struct_data).__name__
    if "MapContainer" in t or "MessageMap" in t:
        try:
            return _convert_proto_to_dict(dict(struct_data))
        except (RecursionError, Exception):
            pass
    try:
        from google.protobuf.json_format import MessageToDict
        if hasattr(struct_data, "pb"):
            return MessageToDict(struct_data.pb)
        if hasattr(struct_data, "DESCRIPTOR"):
            return MessageToDict(struct_data)
    except Exception:
        pass
    try:
        return _convert_proto_to_dict(dict(struct_data))
    except RecursionError:
        return {"_raw": str(struct_data)[:2000]}
    except Exception:
        return {}


def _extract_text_from_field(field_data: Any, _depth: int = 0) -> str:
    if not field_data or _depth > 5:
        return ""
    data = _convert_proto_to_dict(field_data)
    if isinstance(data, str):
        return re.sub(r"<[^>]+>", "", data).strip()
    if isinstance(data, dict):
        for key in ("content", "text", "snippet", "answer", "segment", "value"):
            if data.get(key) and isinstance(data[key], str):
                return re.sub(r"<[^>]+>", "", data[key]).strip()
        for v in data.values():
            if isinstance(v, str) and len(v) > 20:
                return v.strip()
    if isinstance(data, list):
        parts = [_extract_text_from_field(x, _depth + 1) for x in data[:10]]
        return "\n".join(p for p in parts if p)
    return str(data)[:500] if data else ""


def search_rag(query: str, num_results: int = 5) -> dict[str, Any]:
    """Search Vertex AI Search (Discovery Engine). Returns status, results (id, uri, doc_type, title, content, page_reference)."""
    if not config.DATA_STORE_ID:
        return {"status": "ERROR", "query": query, "results": [], "error": "DATA_STORE_ID not set. Set it in .env"}
    try:
        from google.cloud import discoveryengine_v1 as discoveryengine
        from google.api_core.client_options import ClientOptions
    except ImportError:
        return {"status": "ERROR", "query": query, "results": [], "error": "google-cloud-discoveryengine not installed"}
    try:
        cache_key = f"{config.PROJECT_ID}_{config.SEARCH_LOCATION}_{config.DATA_STORE_ID}"
        if cache_key not in _search_client_cache:
            opts = None
            if config.SEARCH_LOCATION != "global":
                opts = ClientOptions(api_endpoint=f"{config.SEARCH_LOCATION}-discoveryengine.googleapis.com")
            _search_client_cache[cache_key] = discoveryengine.SearchServiceClient(
                credentials=config.get_credentials(),
                client_options=opts,
            )
        client = _search_client_cache[cache_key]
        request = discoveryengine.SearchRequest(
            serving_config=_get_serving_config(),
            query=query,
            page_size=num_results,
            content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                    return_snippet=True,
                    max_snippet_count=5,
                ),
                extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                    max_extractive_answer_count=3,
                    max_extractive_segment_count=5,
                ),
            ),
        )
        response = client.search(request, timeout=30.0)
        results = []
        for result in response.results:
            try:
                doc = result.document
                data = _safe_struct_to_dict(doc.derived_struct_data) if doc.derived_struct_data else {}
                if not isinstance(data, dict):
                    data = {}
                uri = data.get("link", data.get("uri", ""))
                title = data.get("title", "") or (Path(uri).stem.replace("-", " ").replace("_", " ") if uri else "") or doc.id
                uri_lower = (uri or "").lower()
                title_lower = (title or "").lower()
                doc_type = "Unknown"
                for dtype, keywords in config.DOC_TYPE_KEYWORDS.items():
                    if any(k in uri_lower for k in keywords) or any(k in title_lower for k in keywords):
                        doc_type = dtype
                        break
                content_parts = []
                page_numbers = set()
                for key in ("extractive_answers", "extractive_segments", "snippets"):
                    for item in (data.get(key) or []):
                        d = _convert_proto_to_dict(item) if not isinstance(item, dict) else item
                        text = _extract_text_from_field(item)
                        if text and len(text) > 10:
                            content_parts.append(text)
                        if isinstance(d, dict) and d.get("pageNumber") is not None:
                            page_numbers.add(str(d["pageNumber"]))
                unique = []
                for p in content_parts:
                    if not any(p in u or u in p for u in unique):
                        unique.append(p)
                content = "\n\n".join(unique[:5])[:4000]
                page_ref = ""
                if page_numbers:
                    sorted_pages = sorted(page_numbers, key=lambda x: int(x) if x.isdigit() else 999)
                    page_ref = f"p.{sorted_pages[0]}" if len(sorted_pages) == 1 else f"pp.{', '.join(sorted_pages[:3])}"
                results.append({
                    "id": doc.id,
                    "uri": uri,
                    "doc_type": doc_type,
                    "title": title,
                    "content": content,
                    "page_reference": page_ref,
                })
            except (RecursionError, Exception) as e:
                logger.debug("Skip result %s: %s", getattr(result.document, "id", ""), e)
                continue
        logger.info("search_rag: query='%s' -> %d results", query[:60], len(results))
        return {"status": "OK", "query": query, "num_results": len(results), "results": results}
    except Exception as e:
        logger.exception("search_rag failed: %s", e)
        return {"status": "ERROR", "query": query, "results": [], "error": str(e)}


def search_procedure(query: str, num_results: int = 5) -> dict[str, Any]:
    """Search and filter for Procedure documents only."""
    result = search_rag(query, num_results * 2)
    if result["status"] != "OK":
        return result
    filtered = [r for r in result["results"] if r["doc_type"] == "Procedure"]
    if not filtered and result["results"]:
        filtered = result["results"]
    return {"status": "OK", "query": query, "num_results": len(filtered), "results": filtered[:num_results]}


def search_guidelines(query: str, num_results: int = 5) -> dict[str, Any]:
    """Search and filter for Guidelines documents only."""
    result = search_rag(query, num_results * 2)
    if result["status"] != "OK":
        return result
    filtered = [r for r in result["results"] if r["doc_type"] == "Guidelines"]
    if not filtered and result["results"]:
        filtered = result["results"]
    return {"status": "OK", "query": query, "num_results": len(filtered), "results": filtered[:num_results]}


def format_procedure_context(query: str, num_results: int = 3) -> str:
    """Return procedure RAG context as a string for prompts."""
    r = search_procedure(query, num_results)
    if r.get("status") != "OK" or not r.get("results"):
        return ""
    return "\n\n".join((x.get("content") or "")[:2000] for x in r["results"] if x.get("content"))
