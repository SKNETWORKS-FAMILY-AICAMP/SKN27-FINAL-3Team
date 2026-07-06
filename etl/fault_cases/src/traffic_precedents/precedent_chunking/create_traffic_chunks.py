from __future__ import annotations

import json

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.config import SETTINGS

from .create_chunks_common import create_chunks


def main() -> None:
    report = create_chunks(db_name=SETTINGS.traffic_db, dataset="traffic")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
