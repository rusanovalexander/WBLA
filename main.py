"""
Credit Pack Multi-Agent PoC v3.2 — Main Entry Point

Run with:
    streamlit run ui/app.py

Or for testing:
    python main.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    setup_environment, validate_config, VERSION,
    PROJECT_ID, DATA_STORE_ID, DATA_FOLDER,
)
from tools.document_loader import scan_data_folder
from tools.rag_search import test_rag_connection


def main():
    """Test configuration and show status."""
    setup_environment()

    print("=" * 60)
    print(f"Credit Pack Multi-Agent PoC v{VERSION}")
    print("=" * 60)

    # Validate config
    print("\n📋 Configuration:")
    config = validate_config()
    for key, ok in config.items():
        if key != "all_ok":
            status = "✅" if ok else "❌"
            print(f"  {status} {key}")

    print(f"\n  Project ID: {PROJECT_ID}")
    print(f"  Data Store: {DATA_STORE_ID}")

    # Test RAG
    print("\n🔗 RAG Connection:")
    rag = test_rag_connection()
    if rag["connected"]:
        print(f"  ✅ Connected to {rag['data_store']}")
        print(f"  Sample doc: {rag.get('sample_doc', 'N/A')}")
    else:
        print(f"  ❌ Failed: {rag.get('error', 'Unknown')}")

    # Scan documents
    print("\n📁 Documents:")
    docs = scan_data_folder()
    for category, files in docs.items():
        if category != "other":
            print(f"  {category}: {len(files)} file(s)")
            for f in files[:2]:
                print(f"    - {Path(f).name}")

    print("\n" + "=" * 60)
    print("To start the UI:")
    print("  streamlit run ui/app.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
