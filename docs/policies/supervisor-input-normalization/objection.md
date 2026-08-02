# 의견제출·이의신청 규칙

| 입력 예시 | 의미 분류 | schema.field | 정규화 값 | 처리 | 금지 조건 | rule_id |
|---|---|---|---|---|---|---|
| 이의를 제기하지 않음 | negation | objection_intake.requested_action | 확정하지 않음 | 재질문 | 부정 표현 | 없음 |
| 의견 제출, 의견제출 | action | objection_intake.requested_action | opinion_submission | 자동 | 원하는 절차가 불확실한 경우 | `objection.requested_action.opinion_submission.exact_01` |
| 이의 제기, 이의 재기 | action | objection_intake.requested_action | objection | 자동 | 부정하거나 다른 절차와 함께 언급한 경우 | `objection.requested_action.objection.typo_01` |
| 납부 안내, 납부 방법 | action | objection_intake.requested_action | payment_guidance | 자동 | 이의 절차를 원하는지 불명확한 경우 | `objection.requested_action.payment_guidance.exact_01` |
| 신호위반 | entity | objection_intake.legal_issue_terms | signal_violation | 자동 | 법적 결론으로 확대하지 않음 | `objection.legal_issue_terms.signal_violation.exact_01` |
| 주정차 위반 | entity | objection_intake.legal_issue_terms | parking_violation | 자동 | 법적 결론으로 확대하지 않음 | `objection.legal_issue_terms.parking_violation.exact_01` |
| 어린이 보호구역, 스쿨존 | entity | objection_intake.legal_issue_terms | school_zone | 자동 | 법적 결론으로 확대하지 않음 | `objection.legal_issue_terms.school_zone.exact_01` |
| 운전자 본인 여부 | entity | objection_intake.legal_issue_terms | driver_identity_dispute | 자동 | 실제 운전자를 추정하지 않음 | `objection.legal_issue_terms.driver_identity_dispute.exact_01` |

사용자가 원하는 절차, 다투는 사실, 이의 사유, 증거와 법률 검색 쟁점만 구조화한다.
