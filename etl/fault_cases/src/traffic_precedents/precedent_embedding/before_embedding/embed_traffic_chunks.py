from __future__ import annotations

import json

from .store_embeddings_common import create_embeddings, parse_args


def main() -> None:
    args = parse_args("Create OpenAI embeddings for traffic precedent chunks.")
    report = create_embeddings(dataset="traffic", limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

