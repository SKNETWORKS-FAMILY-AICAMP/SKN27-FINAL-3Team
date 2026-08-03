# 과태료·범칙금 규칙

| 입력 예시 | 의미 분류 | schema.field | 정규화 값 | 처리 | 금지 조건 | rule_id |
|---|---|---|---|---|---|---|
| 고지서 | state | fine_notice_intake.notice_stage | 확정하지 않음 | 재질문 | 사전통지·납부고지 단계가 불명확함 | 없음 |
| 과태료 | entity | fine_notice_intake.fine_type | fine | 자동 | 범칙금과 함께 언급되어 구분이 필요한 경우 | `fine_notice.fine_type.fine.exact_01` |
| 범칙금 | entity | fine_notice_intake.fine_type | penalty | 자동 | 과태료와 함께 언급되어 구분이 필요한 경우 | `fine_notice.fine_type.penalty.exact_01` |
| 과태료 사전통지서 | state | fine_notice_intake.notice_stage | pre_notice | 자동 | 단계가 부정되거나 불확실한 경우 | `fine_notice.notice_stage.pre_notice.exact_01` |
| 1차 고지서, 1챠 고지서 | state | fine_notice_intake.notice_stage | first_notice | 자동 | 단계가 부정되거나 불확실한 경우 | `fine_notice.notice_stage.first_notice.typo_01` |
| 과태료 납부고지서 | state | fine_notice_intake.notice_stage | payment_notice | 자동 | 단계가 부정되거나 불확실한 경우 | `fine_notice.notice_stage.payment_notice.exact_01` |
| 문서 첨부도 가능 | state | fine_notice_intake.attachment_available | yes | 자동 | 첨부 가능 여부를 부정하거나 불확실하게 표현한 경우 | `fine_notice.attachment_available.yes.exact_01` |

문서 종류, 단계, 발급기관, 날짜, 금액, 납부기한, 첨부 가능 여부와 고지된 위반 사실만 구조화한다.
