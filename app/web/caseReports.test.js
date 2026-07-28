import test from "node:test";
import assert from "node:assert/strict";

import { reportsForCase } from "./caseReports.js";

test("returns only reports linked to the selected case", () => {
  const reports = [
    { report_id: "R-1", metadata: { case_id: "C-1" } },
    { report_id: "R-2", metadata: { case_id: "C-2" } },
  ];

  assert.deepEqual(reportsForCase({ case_id: "C-1", latest_report_id: "R-1" }, reports), [reports[0]]);
  assert.deepEqual(reportsForCase({ case_id: "C-2" }, reports), [reports[1]]);
});

test("returns no report when the case has no report link", () => {
  assert.deepEqual(reportsForCase({ case_id: "C-3" }, [{ report_id: "R-1" }]), []);
});

test("returns no report when no case is selected", () => {
  assert.deepEqual(reportsForCase(null, [{ report_id: "R-1" }]), []);
});
