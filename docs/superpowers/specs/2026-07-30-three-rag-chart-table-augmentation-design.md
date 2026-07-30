# 세 RAG 발표자료 그래프·표 보강 설계

## 목표

기존 10장 발표자료가 흐름도와 숫자 카드에 치우친 문제를 수정한다. 사용자가
처음 제공한 판례·심의사례·인정기준 보고서와 그 하위 `charts/assets`만 사용해,
발표 화면에서도 수치와 비교 근거가 읽히는 12장 자료를 만든다.

## 핵심 원칙

- OCR/Vision 내용은 포함하지 않는다.
- 새 수치를 만들지 않고 세 종합보고서에 기록된 값만 사용한다.
- 수집·정제 전략과 검색 전략은 계속 분리해 설명한다.
- 각 데이터마다 최소 하나의 성능 그래프를 둔다.
- 세 RAG 비교는 카드가 아니라 행과 열이 분명한 표로 제시한다.
- 그래프는 한 화면에서 읽히는 크기를 우선하며, 장식용 축소 이미지를 넣지 않는다.
- 정확도와 후보 회수율, 최종 비율 정확도를 혼용하지 않는다.

## 12장 구성

1. **세 근거의 역할**  
   인정기준·심의사례·판례가 각각 답하는 질문과 Agent 입력을 설명한다.

2. **공통 파이프라인과 데이터별 분기**  
   수집→정제→구조화→청킹→임베딩→검색→평가의 공통 흐름과 세 데이터의
   차이를 보여준다.

3. **인정기준 데이터 구축**  
   4개 PDF→1,109행→277개 Rule→전수 검증 흐름을 보여준다.

4. **인정기준 검색과 단계별 성능 그래프**  
   질문→Top-50→Rule 확인→조건 연결→비율 산정 흐름과 함께 다음 세 막대를
   표시한다.
   - Recall@50: 30/30
   - Rule Hit@1: 22/30
   - Final Ratio Exact: 18/30
   한계는 비율 분기 선택과 수정요소 중복 적용으로 표기한다.

5. **심의사례 데이터 구축**  
   472쪽→226사례→904청크와 사고개요·당사자 주장·주요쟁점·심의판단의
   네 의미 블록을 보여준다.

6. **심의사례 검색 구조**  
   Qwen 후보→사례 collapse→BGE rerank→고유 사례 Top-5 흐름을 설명한다.

7. **심의사례 성능 근거**  
   `08_reranker_metric_comparison`을 크게 배치하고,
   `09_reranker_rank_change`를 보조 그래프로 사용한다.
   핵심 메시지는 Hit@1 20/32→24/32, 기존 정답 강등 0건이다.

8. **판례 수집·품질 게이트**  
   `04_collection_classification_funnel`을 크게 사용해
   17,512 수집 문서→825 판례→3,339 의미 블록을 설명한다.

9. **판례 검색 구조**  
   의미 블록 후보→판례별 통합→Top-200→BGE 의미형 리랭크→Top-5 흐름을
   설명한다.

10. **판례 성능 근거**  
    `06_final_five_way_metrics`를 주 그래프로 사용하고,
    OLD 46.7%→NEW++-BGE 66.7%, nDCG 0.6114→0.7526을 강조한다.

11. **세 RAG 비교표**  
    열은 인정기준·심의사례·판례, 행은 질문·검색 단위·후처리·출력·대표 지표로
    구성한다. 발표자가 세 검색기의 차이를 한 문장으로 설명할 수 있어야 한다.

12. **과실비율 Agent 통합**  
    사고 사실과 세 근거가 Agent로 모이고, 예상 범위·적용 조건·인용 근거·
    불확실성을 출력하는 구조를 보여준다. 단순 평균과 자동 법률판단은 하지
    않는다는 경계를 명시한다.

## 자산 매핑

### 심의사례

- `etl/fault_cases/review_case_test/08_PRESENTATION_REPORT/charts/01_review_case_data_pipeline.png`
- `etl/fault_cases/review_case_test/08_PRESENTATION_REPORT/charts/08_reranker_metric_comparison.png`
- `etl/fault_cases/review_case_test/08_PRESENTATION_REPORT/charts/09_reranker_rank_change.png`

### 판례

- `etl/fault_cases/precedents_test/00_docs/assets/39_precedent_ppt_report/04_collection_classification_funnel.png`
- `etl/fault_cases/precedents_test/00_docs/assets/39_precedent_ppt_report/06_final_five_way_metrics.png`

### 인정기준

별도 그래프 이미지가 없으므로 종합보고서의 R10 지표를 기반으로
PowerPoint 편집 가능한 막대 그래프로 구성한다. 지표 정의는 슬라이드에
직접 표기한다.

## 검증 기준

- 12장, 16:9
- PowerPoint에서 정상 열림
- 12장 모두 PowerPoint 렌더링 성공
- 그래프·표의 제목, 분모, 지표 정의가 원문과 일치
- 텍스트 또는 도형의 슬라이드 경계 이탈 없음
- 각 그래프의 핵심 수치가 발표 화면에서 식별 가능
- 모든 슬라이드 발표자 노트에 `[Sources]` 블록 유지

