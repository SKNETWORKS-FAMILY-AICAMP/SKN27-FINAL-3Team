# 68 MVP Demo Checklist - 2026-07-06

## Goal

Lock the current MVP spine as a repeatable browser demo.

Target flow:

```text
guest enters
-> starts chat session
-> selects upload file
-> logs in with Google mock flow
-> upload continues on the same session_id
-> scan returns clean
-> chat submits with async_worker
-> worker progress is visible
-> report preview/save/download works
-> mypage/history show the same session
```

## Demo Steps

1. Open the frontend app.
   - Expected: entry/chat UI loads without console errors.

2. Start a guest consultation.
   - Expected: a `guest_id` and `session_id` are created.
   - API: `POST /api/auth/guest-session/`

3. Select an image, PDF, or video file.
   - Expected: upload button becomes available.
   - Expected when not logged in: upload copy indicates Google login is required.

4. Continue through Google mock login.
   - Expected: the original `session_id` is retained.
   - API: `POST /api/auth/google/code/`
   - Check: browser keeps app JWT, `auth_session_id`, `guest_id`, and `session_id`.

5. Upload the selected file.
   - Expected: file metadata is stored under the same `session_id`.
   - API: `POST /api/files/`

6. Run file scan.
   - Expected: demo file reaches `scan_status=clean`.
   - API: `POST /api/files/{attachment_id}/scan/`
   - Failure state: non-clean files must not enter Agent input.

7. Submit the chat message with `async_worker`.
   - Expected: response status starts as `queued`.
   - Expected: `progress_state.state=queued`.
   - API: `POST /api/chat/messages/`

8. Process one worker pass in local demo mode.
   - Expected: worker status becomes `success` or a visible partial/failure state.
   - API: `POST /api/agents/work-items/process/`

9. Save and download the report.
   - Expected: `report_quality.v1` is included.
   - Expected: download body includes `analysis_job_status` and `partial_report`.
   - API:
     - `POST /api/reports/`
     - `GET /api/reports/{report_id}/download/`

10. Open My Page and history.
    - Expected: the same `session_id`, `job_id`, and report appear.
    - API:
      - `GET /api/mypage/summary/?session_id={session_id}`
      - `GET /api/history/?session_id={session_id}&job_id={job_id}`

## Blocked State Checks

- Expired guest identity:
  - Expected: `guest_session_invalid`
  - Required action: `refresh_guest_session`

- Pending scan attachment:
  - Expected: `scan_gate.status=blocked`
  - Expected: no `AgentWorkItem` is created.

- Rejected scan attachment:
  - Expected: user must replace the file.
  - Expected: rejected attachment is excluded from Agent input.

- Partial report:
  - Expected: UI shows `partial_report`.
  - Expected: report download includes partial quality metadata.

## Verification Commands

```powershell
python backend\manage.py test chatbot.tests.ChatbotMockApiTests.test_mvp_e2e_demo_spine_upload_worker_report_history
python backend\manage.py test chatbot
python -m pytest test\test_frontend_auth_session_contract.py
npm --prefix app\web run build
git diff --check
```

Optional demo readiness:

```powershell
python backend\manage.py load_legal_rag_smoke_fixture --replace --format text --smoke-query school-zone-smoke
python backend\manage.py check_production_readiness --format text
```

## Not In This Demo Pass

- Real AWS/S3 production connection
- Real Google Cloud Console one-time authorization code smoke
- Full `vision_media_analysis` implementation
- Final PDF/DOCX objection document generation

