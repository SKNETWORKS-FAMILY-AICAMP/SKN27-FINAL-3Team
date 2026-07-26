export function reportsForCase(item = {}, reports = []) {
  const caseId = item.case_id || item.job_id || "";
  const directIds = new Set([item.latest_report_id, item.report_id].filter(Boolean));

  return reports.filter((report) => {
    const reportCaseId = report.case_id || report.metadata?.case_id || "";
    return directIds.has(report.report_id) || Boolean(caseId && reportCaseId === caseId);
  });
}
