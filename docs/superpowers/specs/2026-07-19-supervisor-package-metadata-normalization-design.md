# Supervisor package metadata normalization

## Purpose

Close the remaining #229 follow-up boundary before a Supervisor LLM or fallback
state is persisted. Agent package attachments must retain only stable
`attachment_id` selectors; raw content, object/storage locations, scan fields,
and arbitrary model-supplied metadata must not be stored in the Supervisor
handoff or plan.

## Scope

This change applies to both LLM-normalization paths in
`app/services/supervisor_llm_service.py`:

- conversation state packages from `_safe_agent_input_packages`
- analysis-plan packages from `_safe_plan_agent_packages`

It does not change routing, Agent business rules, external LLM calls, file
storage, or the Worker-time reconstruction introduced by PR #230.

## Design

1. Start with the server-generated fallback package for each approved
   `node_code`; its schema version, node, owner, and allowed payload structure
   remain authoritative.
2. Merge only candidate fields already supported by that fallback payload.
   Candidate-only payload keys are discarded.
3. For `payload.attachments` and package-level `attachments`, replace every
   item with `{ "attachment_id": "..." }`, remove duplicates and invalid IDs,
   and preserve the fallback selector list when the candidate provides no
   usable selectors.
4. Keep existing package status and missing-field normalization rules. A
   malformed package remains invalid under the existing contract validation;
   normalization must not turn an invalid candidate into a valid package.
5. PR #230's Worker boundary remains unchanged. At execution, selector IDs are
   still resolved only against the scan-gated canonical attachment list.

## Error handling

- Unknown packages, invalid package shapes, and duplicate/unknown node codes
  keep following the current fail-closed validation path.
- Invalid attachment entries are dropped rather than copied. No client or LLM
  storage URI/content fallback is introduced.

## Verification

Tests will be written first and must demonstrate that both state and plan
normalization discard `content_base64`, storage URIs, scan metadata, and
candidate-only payload keys while retaining valid `attachment_id` selectors.
The focused Supervisor LLM tests, the #229 Worker-boundary regression tests,
and the relevant Django queue tests will be run before PR preparation.

## Completion criteria

- Stored LLM and fallback package attachments contain selector IDs only.
- Candidate package payloads cannot add fields absent from the server fallback
  contract.
- Existing valid package behavior and Worker-time attachment reconstruction are
  preserved.
- The master checklist records this specific follow-up as in progress until
  merge and CI confirm it.
