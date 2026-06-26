# #58 Django-React mock 연동과 중간 발표 시나리오 검증

| 항목 | 내용 |
|---|---|
| Issue | `#58 chatbot mock integration scenario` |
| Parent | `#55` |
| Related | `#40`, `#56`, `#57` |
| Scope | mock API fixture와 React mock 화면이 하나의 사용자 시나리오로 연결되는지 검증 |
| Status | pytest 검증 초안 |
| 작성일 | 2026-06-26 |

## 1. 선택 시나리오

중간 발표용 기본 시나리오는 과태료 고지서 분석 후 이의신청서 초안 action까지 이어지는 흐름으로 고정한다.

1. 사용자가 챗봇에 고지서 관련 질문을 입력한다.
2. 사용자가 고지서 이미지 attachment metadata를 함께 보낸다.
3. mock service가 `fine_notice`, `law_ground`, `objection_report` 카드를 반환한다.
4. 사용자가 리포트 저장 또는 다운로드 action을 누른다.
5. mock report action이 `report_id`, `case_id`, `status`, `download_url` 후보를 반환한다.

추가로 과실비율 흐름은 MCP/외부 조회 없이 사고 설명 기반 mock 결과만 확인한다.

1. 사용자가 사고 경위 또는 과실비율 질문을 입력한다.
2. mock service가 `fault_ratio` routing intent를 반환한다.
3. `fault_ratio`, `similar_case`, `recommended_evidence` 카드를 표시할 수 있는 응답을 반환한다.
4. `structured_result`에는 사고 유형 후보, 쟁점 태그, 유사 사례, 신뢰도, 정성 라벨, 한계 문구를 포함한다.
5. 과실비율 수치 확정 표현은 사용하지 않는다.

## 2. 추가 파일

| 파일 | 역할 |
|---|---|
| `test/test_chatbot_mock_service.py` | mock service 성공/부분/리포트 action 검증 |

## 3. 검증 명령

```powershell
python -m pytest test/test_chatbot_mock_service.py
```

## 4. 통과 기준

- 고지서 success 흐름에서 `fine_notice`, `objection_report` 카드가 반환된다.
- partial 흐름에서 추가 질문이 반환되고 report action은 비활성화 가능한 상태가 된다.
- download action에서 `download_url`이 반환된다.
- 실제 Agent/RAG/MCP 호출 없이 mock fixture만으로 동작한다.
- 과실비율 흐름에서 `fault_ratio`, `similar_case`, `recommended_evidence` 카드와 `similar_cases` schema가 반환된다.
- 과실비율 수치 확정 문구가 아니라 `ratio_range_label`과 `limitations`로 표시된다.

## 5. 남은 검증

- 실제 Django URLConf 연결 후 endpoint 호출 검증
- 실제 React build 환경에서 컴포넌트 렌더링 검증
- `#40` Cross-MVP 통합 시나리오와 evidence schema 정렬
- 로그인/JWT 실패 흐름 연결

