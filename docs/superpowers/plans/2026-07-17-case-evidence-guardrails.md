# Case evidence guardrails implementation plan

> Issue: #221 — Supervisor 사실·주장·미확인 정보 분리 가드레일
> Branch: `feat/221-case-evidence-guardrails`

## Goal

Introduce a non-breaking `case_evidence.v1` boundary that distinguishes
materially supported facts, user claims, and unknown/conflicting items.  The
case-analysis queue must use only materially supported facts as its factual
input and must return an actionable readiness error when required material
evidence is missing.

## Implementation steps

- [x] Add a pure evidence-classification service and unit tests for material,
  user-confirmed, missing, and conflicting inputs.
- [x] Expose the latest `case_evidence.v1` from the case workspace contract
  without changing `confirmed_facts.v1` responses.
- [x] Gate case-analysis dispatch on required material evidence; keep user
  claims and unknowns in context, but do not serialize them into agent
  `user_text` / `context.user_facts`.
- [x] Require `case_evidence.v1` in the analysis plan and carry it in each
  queued worker payload.
- [x] Add repository/API regression tests for the blocked and allowed paths.
- [x] Update the full project readiness checklist for #220 merged and #221
  in progress; run focused and relevant regression suites.

## Compatibility decisions

- `confirmed_facts.v1` remains the user-confirmed case record and is not
  renamed or expanded.
- `user_statement`, `user_confirmation`, missing source metadata, and
  conflicts are never material facts. They remain visible as claims or
  unknowns and lead to a safe `fact_readiness_not_met` response until the
  required evidence is provided.
- Material source types are explicit: `attachment`, `official_document`,
  `official_record`, `ocr_verified`, and `material_confirmed`; at the Case
  execution boundary their `source_ref` must also match a `ready`, case-owned
  uploaded file.
