"""
Extract HAS_PENALTY and HAS_APPENDIX relationships from law chunks.
"""
import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

def main():
    chunks_path = Path("output/law_ingestion/chunks/law_chunks.jsonl")
    out_path = Path("output/law_ingestion/relations/law_extra_relations.jsonl")
    
    if not chunks_path.exists():
        print(f"Error: {chunks_path} not found.")
        return

    # 1. Build Mapping
    print("1. Building article/appendix mapping...")
    article_map = defaultdict(list)
    appendix_map = defaultdict(list)
    
    with open(chunks_path, 'r', encoding='utf-8') as f:
        for line in f:
            chunk = json.loads(line)
            sv_id = chunk.get("source_version_id")
            chunk_id = chunk.get("chunk_id")
            art_no = chunk.get("article_no")
            app_no = chunk.get("appendix_no")
            
            if sv_id and chunk_id:
                if art_no:
                    article_map[(sv_id, art_no)].append(chunk_id)
                if app_no:
                    # Normalize "별표 1" -> "별표1"
                    norm_app = app_no.replace(" ", "")
                    appendix_map[(sv_id, norm_app)].append(chunk_id)

    # 2. Extract Relations
    print("2. Extracting relations...")
    penalty_keywords = ["벌금", "과태료", "징역", "처한다", "부과한다", "범칙금"]
    article_pattern = re.compile(r"제(\d+(?:의\d+)?)조")
    appendix_pattern = re.compile(r"별표\s*(\d+(?:의\d+)?)")
    
    extra_relations = []
    penalty_count = 0
    appendix_count = 0
    
    with open(chunks_path, 'r', encoding='utf-8') as f:
        for line in f:
            chunk = json.loads(line)
            sv_id = chunk.get("source_version_id")
            current_chunk_id = chunk.get("chunk_id")
            text = chunk.get("provision_text", "")
            
            if not sv_id or not current_chunk_id or not text:
                continue
                
            # Check Penalty
            if any(k in text for k in penalty_keywords):
                # Find all referenced articles
                refs = article_pattern.findall(text)
                for ref in set(refs):
                    art_key = f"제{ref}조"
                    target_chunks = article_map.get((sv_id, art_key), [])
                    for t_id in target_chunks:
                        if t_id != current_chunk_id:
                            extra_relations.append({
                                "relation_id": f"rel_pen_{t_id}_{current_chunk_id}",
                                "relation_type": "HAS_PENALTY",
                                "from_chunk_id": t_id,
                                "to_chunk_id": current_chunk_id,
                                "confidence": 0.9,
                                "evidence_text": "Regex match for penalty reference",
                                "created_at": datetime.now(timezone.utc).isoformat()
                            })
                            penalty_count += 1

            # Check Appendix
            app_refs = appendix_pattern.findall(text)
            for ref in set(app_refs):
                app_key = f"별표{ref}"
                target_chunks = appendix_map.get((sv_id, app_key), [])
                for t_id in target_chunks:
                    if t_id != current_chunk_id:
                        extra_relations.append({
                            "relation_id": f"rel_app_{current_chunk_id}_{t_id}",
                            "relation_type": "HAS_APPENDIX",
                            "from_chunk_id": current_chunk_id,
                            "to_chunk_id": t_id,
                            "confidence": 0.9,
                            "evidence_text": "Regex match for appendix reference",
                            "created_at": datetime.now(timezone.utc).isoformat()
                        })
                        appendix_count += 1

    # 3. Save
    print(f"3. Saving {len(extra_relations)} relations...")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        for rel in extra_relations:
            f.write(json.dumps(rel, ensure_ascii=False) + '\n')
            
    print(f"Done. Found {penalty_count} HAS_PENALTY and {appendix_count} HAS_APPENDIX relations.")
    print(f"File saved to {out_path}")

if __name__ == "__main__":
    main()
