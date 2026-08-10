# Phase 0 Verification Matrix

## Current authority

This is the single current A–G verification matrix. Earlier C/G support-only
and D2-pending descriptions are superseded and are not acceptance evidence.

| Flow | Production path under test | Persisted/state assertion | Blocking evidence |
|---|---|---|---|
| A | guest session -> Google login -> same consultation resume | guest/auth ownership is promoted only for the matching session | Phase 0 core user-flow characterization gate |
| B | upload -> quarantine/scan -> clean attachment -> classification workflow | `UploadedFile` quarantine/scan state; D2 file-scan worker consumption | core gate plus Compose integration gate |
| C | OCR-confirmed fine notice -> short answer -> law worker -> result | matching attachment-bound OCR state, plan/queue/message/job/work-item bindings, `AgentResult` and `RetrievalEvent`; replacement B cannot reuse A | core gate; new stale-OCR test; deterministic service-contract gate; sensitivity negative control |
| D | accident intake -> confirmation -> Case -> queue | `Case`, `ConfirmedFactVersion`, `AnalysisJob`, and `AgentWorkItem` binding | Phase 0 core user-flow characterization gate |
| E | confirmed facts -> analysis job -> worker -> persisted result | worker claim and persisted `AgentResult` | core gate plus Compose agent-worker probe |
| F | stale lease or stopped worker -> safe reclaim/retry | one terminal work result without unsafe duplicate execution | Phase 0 core user-flow characterization gate |
| G | worker report -> user confirmation -> owner-only DOCX download | case/fact/job/work-item/result/display/report provenance and confirmation state | core gate; deterministic service-contract gate; sensitivity negative control |

The C/G service-level and pipeline-level doubles are not provider-leaf claims.
Their internal contracts are blocking through the deterministic
service-contract gate, while their HTTP, routing, planning, queue, worker,
persistence, authorization, confirmation, rendering, and download boundaries
remain production implementations.

## Docker boundary

| Scope | Current result | Evidence |
|---|---|---|
| D1 image build and import smoke | PASS | `production-gate` Run `30861528733`, Job `91844345278`; the approved-base tree was equivalent |
| D2 Compose service integration | PASS | historical C/G `production-gate` Run `31317365628`, compose Job `93255063276`, `phase-00-compose-evidence` artifact reported `status=pass` |

Each new PR head must rerun the blocking workflow. For the corrected Compose
receipt, success additionally requires no `failed-step.txt`,
`last-step.txt=compose-final`, and `cleanup.txt` containing `cleanup_success`.
