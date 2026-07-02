from typing import Any

def validate_input_envelope(context: dict[str, Any]) -> dict[str, Any]:
    """
    Handoff Input(Temporal) 검증
    """
    import re
    errors = []
    temporal = context.get("temporal_basis", {})
    if temporal.get("mode") == "as_of":
        effective_at = temporal.get("effective_at")
        if not effective_at:
            errors.append("temporal_basis가 'as_of'이나 effective_at이 누락되었습니다.")
        elif not re.match(r"^\d{4}-\d{2}-\d{2}$", str(effective_at)):
            errors.append(f"effective_at 형식이 올바르지 않습니다(YYYY-MM-DD): {effective_at}")
        
    return {"valid": len(errors) == 0, "errors": errors}

def validate_and_filter_provisions(
    provisions: list[dict[str, Any]], 
    scope: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    법률 에이전트 전용 하드 필터링 (순수 법령 내에서의 통제)
    """
    limitations = []
    valid_provisions = []
    
    # 순수 법령 도메인 내에서의 허용 범위만 검사 (판례/뉴스 등 타 도메인 검사 제외)
    for prov in provisions:
        # 2. 필수 필드 누락 검사 (원문 및 출처 URL 필수)
        if not prov.get("provision_text") or not prov.get("source_url"):
            limitations.append(f"필수 필드(원문 또는 URL) 누락으로 제거됨: {prov.get('chunk_id')}")
            continue
            
        valid_provisions.append(prov)
        
    return valid_provisions, limitations
