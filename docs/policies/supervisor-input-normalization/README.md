# Supervisor 입력 정규화 Wiki

이 디렉터리는 사고 과실상담과 과태료·범칙금·이의신청 입력 규칙을 사람이 검토할 수
있게 설명한다. 실행의 유일한 기준은
`app/config/supervisor_input_normalization_policy.v1.json`이다.

- JSON 정책과 Wiki의 rule ID는 항상 같은 변경에서 갱신한다.
- 규칙 변경에는 회귀 테스트를 함께 추가한다.
- 운영 중 동적 편집이나 관리자 UI는 제공하지 않는다.
- 정규화 규칙은 법률 결론, 과실비율, 법령·판례를 생성하지 않는다.
