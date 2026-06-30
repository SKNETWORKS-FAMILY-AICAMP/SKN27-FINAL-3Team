from typing import Any

def validate_input_envelope(context: dict[str, Any]) -> dict[str, Any]:
    """
    Handoff Input(Temporal) 검증
    """
    errors = []
    temporal = context.get("temporal_basis", {})
    if temporal.get("mode") == "as_of" and not temporal.get("effective_at"):
        errors.append("temporal_basis가 'as_of'이나 effective_at이 누락되었습니다.")
        
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
    allowed_sources = scope.get("allowed_source_types", [])
    
    for prov in provisions:
        source_type = prov.get("source_type")
        
        # 1. 허용된 법령 종류(법률, 시행령 등) 필터링
        if allowed_sources and source_type not in allowed_sources:
            continue
            
        # 2. 필수 필드 누락 검사 (원문 및 출처 URL 필수)
        if not prov.get("provision_text") or not prov.get("source_url"):
            limitations.append(f"필수 필드(원문 또는 URL) 누락으로 제거됨: {prov.get('chunk_id')}")
            continue
            
        valid_provisions.append(prov)
        
    return valid_provisions, limitations
