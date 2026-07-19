"""Explicitly initialize the configured embedding provider."""

from __future__ import annotations

import argparse
import json

from app.index.embedder import embedding_status, get_embeddings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report status without downloading or calling an API",
    )
    args = parser.parse_args()

    status = embedding_status()
    print(json.dumps(status, ensure_ascii=False))
    if status["ready"]:
        return 0
    if args.check:
        return 1
    if status["provider"] != "local":
        print("The configured remote embedding provider is not ready; check its API key.")
        return 1

    print("Initializing all-MiniLM-L6-v2. The first download is about 80 MB...")
    get_embeddings().embed_query("embedding model initialization")
    final_status = embedding_status()
    print(json.dumps(final_status, ensure_ascii=False))
    return 0 if final_status["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
