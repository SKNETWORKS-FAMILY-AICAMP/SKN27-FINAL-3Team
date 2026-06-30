"""법률 텍스트 전처리, XML 구조 파싱, 문맥 청킹 분할 및 메타데이터 보강을 묶어서 담당하는 통합 파서 모듈입니다."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


# ==========================================
# 1. 텍스트 정제 및 전처리 영역 (Preprocessor)
# ==========================================

def preprocess_raw_documents(raw_records: list[dict]) -> list[dict]:
    """수집된 모든 법령 레코드의 원본 텍스트를 전처리합니다."""
    return [preprocess_raw_document(row) for row in raw_records]


def preprocess_raw_document(raw_document: dict) -> dict:
    """XML 태그를 걷어내고 공백과 개행 문자를 깔끔하게 정제합니다."""
    text = str(raw_document.get("content", ""))
    text = re.sub(r"<[^>]+>", " ", text) # HTML/XML 태그 제거
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return {**raw_document, "normalized_text": text.strip()}


# ==========================================
# 2. 구조 파싱 및 문장 분할 영역 (Structure Parser)
# ==========================================

# 조문 식별자 매칭용 정규식
ARTICLE_PATTERN = re.compile(r"(제\s*\d+\s*조(?:의\s*\d+)?)(?:\s*\(([^)]+)\))?")
# 청크 쪼개기 기준 글자 수
MAX_APPENDIX_CHARS = 1800
# 청크 분할 시 문맥 보존용 중복 영역 (2줄 오버랩)
APPENDIX_OVERLAP_LINES = 2


def parse_all(preprocessed_documents: list[dict]) -> list[dict]:
    """전체 전처리 완료된 법령들을 구조 단위로 파싱하여 조각 구조체 목록으로 변환합니다."""
    structures: list[dict] = []
    for document in preprocessed_documents:
        structures.extend(parse_structures(document))
    return structures


def parse_structures(preprocessed_document: dict) -> list[dict]:
    """개별 문서를 포맷에 따라 파싱하여 조문 또는 별표 단위 구조로 쪼갭니다."""
    if preprocessed_document.get("raw_format") == "xml":
        return parse_law_xml_structures(preprocessed_document)

    text = preprocessed_document.get("normalized_text", "")
    matches = list(ARTICLE_PATTERN.finditer(text))
    
    if not matches and text:
        segments = split_long_text(text)
        return [
            {
                **_doc_ref(preprocessed_document),
                "chunk_type": "document",
                "article_no": None,
                "article_title": None,
                "paragraph_no": None,
                "item_no": None,
                "appendix_no": None,
                "form_no": None,
                "structure_id": f"document:part{index:03d}" if len(segments) > 1 else "document:1",
                "segment_no": index if len(segments) > 1 else None,
                "provision_text": segment,
            }
            for index, segment in enumerate(segments, 1)
        ]

    structures = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        provision_text = text[start:end].strip()
        article_no = re.sub(r"\s+", "", match.group(1))
        segments = split_long_text(provision_text)
        for segment_index, segment in enumerate(segments, 1):
            structures.append(
                {
                    **_doc_ref(preprocessed_document),
                    "chunk_type": "article",
                    "article_no": article_no,
                    "article_title": match.group(2),
                    "paragraph_no": None,
                    "item_no": None,
                    "appendix_no": None,
                    "form_no": None,
                    "structure_id": f"article:{index + 1}:part{segment_index:03d}" if len(segments) > 1 else f"article:{index + 1}",
                    "segment_no": segment_index if len(segments) > 1 else None,
                    "provision_text": segment,
                }
            )
    return structures


def parse_law_xml_structures(preprocessed_document: dict) -> list[dict]:
    """법제처 공식 법령 XML 데이터에서 조문단위와 별표단위를 추출합니다."""
    try:
        root = ET.fromstring(str(preprocessed_document.get("content", "")).encode("utf-8"))
    except ET.ParseError:
        return []

    if _tag(root) == "AdmRulService":
        return parse_administrative_rule_xml(preprocessed_document, root)

    structures = []

    # 1. 표준 조문(조문단위) 파싱
    for article in _iter_by_tag(root, "조문단위"):
        if _child_text(article, "조문여부") != "조문":
            continue
        article_no = _article_no(article)
        provision_parts = _article_text_parts(article)
        provision_text = "\n".join(part for part in provision_parts if part).strip()
        if not article_no or not provision_text:
            continue
        article_key = article.attrib.get("조문키") or article_no
        segments = split_long_text(provision_text)
        for index, segment in enumerate(segments, 1):
            structures.append(
                {
                    **_doc_ref(preprocessed_document),
                    "chunk_type": "article",
                    "article_no": article_no,
                    "article_title": _child_text(article, "조문제목"),
                    "paragraph_no": None,
                    "item_no": None,
                    "appendix_no": None,
                    "form_no": None,
                    "structure_id": f"{article_key}:part{index:03d}" if len(segments) > 1 else article_key,
                    "segment_no": index if len(segments) > 1 else None,
                    "provision_text": segment,
                }
            )

    # 2. 별표/서식(별표단위) 파싱
    for appendix in _iter_by_tag(root, "별표단위"):
        appendix_no_raw = _child_text(appendix, "별표번호")
        appendix_sub_no = _child_text(appendix, "별표가지번호")
        appendix_title = _child_text(appendix, "별표제목")
        appendix_content = _child_text(appendix, "별표내용")

        if not appendix_content and not appendix_title:
            continue

        category = _child_text(appendix, "별표구분") or "별표"

        num_str = str(int(appendix_no_raw)) if appendix_no_raw and appendix_no_raw.isdigit() else (appendix_no_raw or "")
        sub_str = f"의{int(appendix_sub_no)}" if appendix_sub_no and appendix_sub_no.isdigit() and int(appendix_sub_no) > 0 else ""
        disp_no = f"{category}{num_str}{sub_str}" if num_str else category

        base_structure = {
            **_doc_ref(preprocessed_document),
            "chunk_type": "appendix" if category == "별표" else "form",
            "article_no": None,
            "article_title": appendix_title,
            "paragraph_no": None,
            "item_no": None,
            "appendix_no": disp_no if category == "별표" else None,
            "form_no": disp_no if category == "서식" else None,
        }
        appendix_key = appendix.attrib.get("별표키") or disp_no
        full_text = f"{disp_no} {appendix_title or ''}\n{appendix_content or ''}".strip()
        segments = split_long_text(full_text)
        for index, segment in enumerate(segments, 1):
            structures.append(
                {
                    **base_structure,
                    "structure_id": f"{appendix_key}:part{index:03d}",
                    "segment_no": index if len(segments) > 1 else None,
                    "provision_text": segment,
                }
            )

    return structures


def parse_administrative_rule_xml(
    preprocessed_document: dict, root: ET.Element
) -> list[dict]:
    """행정규칙 XML 포맷을 분석하여 파싱합니다."""
    rule_name = _descendant_text(root, "행정규칙명")
    text = _descendant_text(root, "조문내용")
    if not text:
        return []

    matches = list(ARTICLE_PATTERN.finditer(text))
    if not matches:
        segments = split_long_text(text.strip())
        return [
            {
                **_doc_ref(preprocessed_document),
                "source_name": rule_name,
                "chunk_type": "document",
                "article_no": None,
                "article_title": None,
                "paragraph_no": None,
                "item_no": None,
                "appendix_no": None,
                "form_no": None,
                "structure_id": f"document:part{index:03d}" if len(segments) > 1 else "document:1",
                "segment_no": index if len(segments) > 1 else None,
                "provision_text": segment,
            }
            for index, segment in enumerate(segments, 1)
        ]

    structures = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        article_no = re.sub(r"\s+", "", match.group(1))
        segments = split_long_text(text[start:end].strip())
        for segment_index, segment in enumerate(segments, 1):
            structures.append(
                {
                    **_doc_ref(preprocessed_document),
                    "source_name": rule_name,
                    "chunk_type": "article",
                    "article_no": article_no,
                    "article_title": match.group(2),
                    "paragraph_no": None,
                    "item_no": None,
                    "appendix_no": None,
                    "form_no": None,
                    "structure_id": f"article:{index + 1}:part{segment_index:03d}" if len(segments) > 1 else f"article:{index + 1}",
                    "segment_no": segment_index if len(segments) > 1 else None,
                    "provision_text": segment,
                }
            )
    return structures


def split_long_text(text: str, max_chars: int = MAX_APPENDIX_CHARS) -> list[str]:
    """장문의 텍스트를 줄바꿈 및 마침표 단위 경계를 지키며 분할하고 오버랩을 적용합니다."""
    normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(normalized) <= max_chars:
        return [normalized] if normalized else []

    lines = [line.rstrip() for line in normalized.splitlines()]
    segments: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current and current_len + line_len > max_chars:
            segments.append("\n".join(current).strip())
            current = current[-APPENDIX_OVERLAP_LINES:] if APPENDIX_OVERLAP_LINES else []
            current_len = sum(len(item) + 1 for item in current)

        if line_len > max_chars:
            if current:
                segments.append("\n".join(current).strip())
                current = []
                current_len = 0
            segments.extend(_split_long_line(line, max_chars))
            continue

        current.append(line)
        current_len += line_len

    if current:
        segments.append("\n".join(current).strip())

    return [segment for segment in segments if segment]


def _split_long_line(line: str, max_chars: int) -> list[str]:
    parts = re.split(r"(?<=[.。])\s+", line)
    if len(parts) == 1:
        return [line[index : index + max_chars].strip() for index in range(0, len(line), max_chars)]

    segments: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current} {part}".strip()
        if current and len(candidate) > max_chars:
            segments.append(current)
            current = part
        else:
            current = candidate
    if current:
        segments.append(current)
    return segments


def _doc_ref(document: dict) -> dict:
    return {
        "source_id": document["source_id"],
        "source_version_id": document["source_version_id"],
        "raw_document_id": document["raw_document_id"],
        "source_url": document.get("source_url"),
    }


def _iter_by_tag(root: ET.Element, tag_name: str):
    for element in root.iter():
        if _tag(element) == tag_name:
            yield element


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, tag_name: str) -> str | None:
    for child in element:
        if _tag(child) == tag_name and child.text:
            return child.text.strip()
    return None


def _descendant_text(element: ET.Element, tag_name: str) -> str | None:
    for child in element.iter():
        if _tag(child) == tag_name and child.text:
            return child.text.strip()
    return None


def _article_no(article: ET.Element) -> str | None:
    number = _child_text(article, "조문번호")
    if not number:
        return None
    extra = _child_text(article, "조문가지번호")
    suffix = f"의{extra}" if extra and extra != "0" else ""
    return f"제{number}{suffix}조"


def _article_text_parts(article: ET.Element) -> list[str]:
    parts = []
    article_text = _child_text(article, "조문내용")
    if article_text:
        parts.append(article_text)

    for element in article.iter():
        tag = _tag(element)
        if tag in {"항내용", "호내용", "목내용"} and element.text:
            parts.append(element.text.strip())
    return parts


# ==========================================
# 3. 청크 데이터 생성 및 문맥 보존 조립 (Chunk Builder)
# ==========================================

def build_chunks(structures: list[dict], sources: list[dict], versions: list[dict]) -> list[dict]:
    """조각화된 구조체에 상위 법령 이름, 조문 번호 등을 결합해 검색에 용이한 청크로 가공합니다."""
    source_by_id = {source["source_id"]: source for source in sources}
    version_by_id = {version["source_version_id"]: version for version in versions}
    chunks = []

    for structure in structures:
        source = source_by_id[structure["source_id"]]
        version = version_by_id[structure["source_version_id"]]
        normalized_text = normalize_search_text(structure["provision_text"])
        chunk = {
            "chunk_id": build_chunk_id(structure),
            "source_ref": build_source_ref(structure),
            "source_id": source["source_id"],
            "source_name": structure.get("source_name") or source["source_name"],
            "source_type": source["source_type"],
            "source_version_id": version["source_version_id"],
            "mst": version.get("mst"),
            "chunk_type": structure["chunk_type"],
            "article_no": structure.get("article_no"),
            "article_title": structure.get("article_title"),
            "paragraph_no": structure.get("paragraph_no"),
            "item_no": structure.get("item_no"),
            "appendix_no": structure.get("appendix_no"),
            "form_no": structure.get("form_no"),
            "structure_id": structure.get("structure_id"),
            "segment_no": structure.get("segment_no"),
            "provision_text": structure["provision_text"],
            "normalized_text": normalized_text,
            "embedding_text": "",
            "embedding_text_hash": "",
            "source_url": structure.get("source_url"),
            "enforce_date": version.get("enforce_date"),
            "expire_date": version.get("expire_date"),
            "content_hash": "",
            "parse_status": "success",
            "validation_status": "pending",
            "is_searchable": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        chunk["embedding_text"] = build_embedding_text(chunk)
        chunk["embedding_text_hash"] = hash_text(chunk["embedding_text"])
        chunk["content_hash"] = build_content_hash(chunk)
        chunks.append(chunk)

    return chunks


def build_chunk_id(structure: dict) -> str:
    locator = structure.get("article_no") or structure.get("appendix_no") or structure.get("form_no") or "document"
    structure_id = structure.get("structure_id") or locator
    parts = [
        structure["source_version_id"],
        structure["chunk_type"],
        locator,
        structure_id,
    ]
    return ":".join(_safe_id_part(str(part)) for part in parts if part)


def build_source_ref(structure: dict) -> str:
    locator = structure.get("article_no") or structure.get("appendix_no") or structure.get("form_no") or "document"
    return "/".join(
        [
            structure["source_id"],
            structure["source_version_id"],
            structure["chunk_type"],
            locator,
            structure.get("structure_id") or locator,
        ]
    )


def build_content_hash(chunk: dict) -> str:
    return hash_text(
        "|".join(
            [
                str(chunk.get("source_version_id")),
                str(chunk.get("chunk_type")),
                str(chunk.get("article_no") or chunk.get("appendix_no") or chunk.get("form_no")),
                str(chunk.get("structure_id")),
                str(chunk.get("segment_no")),
                str(chunk.get("normalized_text")),
            ]
        )
    )


def build_embedding_text(chunk: dict) -> str:
    """'[법령명 조문번호 제목] 본문' 형태의 임베딩 전용 접두 문구를 생성합니다."""
    title = " ".join(
        value
        for value in [
            chunk.get("source_name"),
            chunk.get("article_no") or chunk.get("appendix_no") or chunk.get("form_no"),
            chunk.get("article_title"),
        ]
        if value
    )
    return f"[{title}] {chunk['normalized_text']}".strip()


def normalize_search_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_id_part(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_.:-]+", "_", value.strip())


# ==========================================
# 4. 데이터 메타데이터 보강 영역 (Metadata Enricher)
# ==========================================

def enrich_metadata(chunks: list[dict]) -> list[dict]:
    """검색 필터에 기여할 도메인 태그(예: 개인형 이동장치, 음주운전)를 분석하여 할당합니다."""
    import yaml
    from pathlib import Path

    # law_query_terms.yaml 로드 시도
    hint_file = Path("storage/rag/law_query_terms.yaml")
    terms = []
    if hint_file.exists():
        try:
            data = yaml.safe_load(hint_file.read_text(encoding="utf-8-sig")) or {}
            terms = data.get("terms") or []
        except Exception as exc:
            print(f"Warning: Failed to load hint terms from {hint_file}: {exc}")

    enriched = []
    for chunk in chunks:
        text = chunk.get("normalized_text", "")
        domain_tags = set()
        
        # 1. law_query_terms.yaml 기반의 매칭 수행
        for term in terms:
            canonical = term.get("canonical")
            user_terms = term.get("user_terms") or []
            search_terms = term.get("search_terms") or []
            
            # canonical 용어, 사용자 용어, 혹은 검색어가 청크에 존재하는지 확인
            all_match_candidates = [canonical] + user_terms + search_terms
            for candidate in all_match_candidates:
                if candidate and candidate in text:
                    domain_tags.add(canonical)
                    break
        
        # 2. 기본 도메인 태그 폴백 유지 (교통, 안전)
        if "교통" in text:
            domain_tags.add("traffic")
        if "안전" in text:
            domain_tags.add("safety")
            
        enriched.append({**chunk, "domain_tags": sorted(list(domain_tags))})
    return enriched

