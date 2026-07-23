# Non-DL analysis to Reporting production smoke

`smoke_non_dl_analysis_reporting_pipeline` verifies one real, uniquely identified
canonical worker run across this boundary:

`fine_notice_analysis -> law_ground_search -> text_ml_case_search -> appeal_decision_flow -> persisted Supervisor handoff -> objection_report_generation -> Report/AnalysisDisplayResult`

The plan intentionally excludes `vision_media_analysis`. The command does not
create fixture `AgentResult`, handoff, report, or display rows. It enqueues through
`enqueue_analysis_job_work`, runs the stored work item through
`process_agent_work_item`, and verifies the rows produced by that path.

## Cost and safety gate

The command exits before enqueueing or creating a smoke session unless
`--allow-paid-provider-call` is present. Supplying the flag is explicit consent to
one new smoke job whose configured analysis adapters may call paid providers.
Every run uses a new session, job, plan, and message identifier; successful rows
remain in the database as audit evidence.

The fine-notice adapter also requires a sanitized, operator-reviewed acceptance
file already promoted to the clean S3 namespace. Upload it through the normal
quarantine/scan/promotion path, review that it contains no real personal data,
then place it under `canonical/acceptance/`. The command rejects quarantine
objects, path traversal, URL query/fragment selectors, and unsupported file
types before it creates or enqueues any job.

Run the strict production check with:

```powershell
python backend/manage.py smoke_non_dl_analysis_reporting_pipeline `
  --allow-paid-provider-call `
  --require-real-agent-results `
  --require-persisted-handoff `
  --require-report `
  --fine-notice-fixture-s3-uri "s3://<clean-bucket>/canonical/acceptance/<reviewed-file>.png" `
  --timeout-seconds 180 `
  --format json
```

Do not put API keys on the command line. Configure provider, PostgreSQL,
pgvector RAG, and object-storage settings through the deployment secret/runtime
environment before running it.

## What strict mode proves

- all four declared non-DL analysis nodes and Reporting produced result rows;
- the canonical job and every analysis/Reporting `AgentResult` finished with
  `success`; a terminal `partial` job is not an operational pass;
- each analysis row has the registered production sync-adapter trace, no adapter
  name containing `mock`, and no declared heuristic fallback;
- each required analysis `AgentResult.created_at` is no later than the durable
  Reporting paid-dispatch guard's `started_at`;
- the persisted `supervisor_reporting_handoff.v1` source IDs exactly identify the
  persisted analysis rows;
- the Reporting row contains the same handoff ID, source fingerprint, gate status,
  and result IDs;
- exactly one `Report` and one `AnalysisDisplayResult` exist for the smoke job,
  the report is `ready`, and general-analysis download metadata is unavailable;
- the analysis and Reporting paid-phase guards are unique, and calling the
  terminal work item again is skipped without creating another guard.

The JSON output contains only identifiers, statuses, counts, and booleans; it does
not print prompts, provider responses, report bodies, or credentials.

## Failure interpretation

- `real_agent_results`: an adapter failed, a non-sync/mock adapter was used, or the
  result was partial, the text case-search path reported a pgvector source as
  unavailable, or a non-production adapter ran. Check the production RAG
  seed/readiness before retrying with a **new** smoke job.
- `job_success` or `all_agent_results_success`: at least one real pipeline phase
  completed only partially; do not accept a draft as an operating success.
- `analysis_persisted_before_reporting`, `persisted_handoff`, or
  `persisted_handoff_consumed`: do not publish the report pipeline; investigate the
  canonical worker checkpoints and handoff provenance.
- `report_persisted`, `report_ready`, `general_report_download_unavailable`, or
  `analysis_display_persisted`: Reporting returned but the final ready bundle did
  not complete, or a general analysis report exposed a download path.
- `safe_retry_no_new_paid_invocation`: stop automatic retries and inspect the
  paid-call guard rows.

The command invokes the canonical worker synchronously, then polls the database
for a bounded terminal-state interval. Provider HTTP cancellation remains governed
by each adapter/client timeout; `--timeout-seconds` does not forcibly interrupt an
in-flight provider call.

## Deliberate remaining gap

This smoke uses an explicit canonical plan to isolate and verify the persisted
Supervisor handoff and worker sequence. It does **not** exercise the optional
conversational Supervisor LLM planner. Validate that boundary separately with
`smoke_supervisor_llm --require-used --require-slot-state`; passing either command
must not be reported as proof that the other boundary passed.
