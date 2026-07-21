"""인정기준 RAG 서비스 진입점"""

from etl.fault_cases.rag_runtime.contracts import RagRequest, DomainSearchResult
from .retriever import search_fault_standard

def handle_request(request: RagRequest) -> DomainSearchResult:
    """에이전트로부터 전달받은 공통 RagRequest를 처리하여 DomainSearchResult를 반환한다."""
    return search_fault_standard(request)
