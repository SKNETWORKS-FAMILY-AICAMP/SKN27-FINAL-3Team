import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("lists authenticated owner reports without narrowing to the active session", async () => {
  const source = await readFile(new URL("./apiClient.js", import.meta.url), "utf8");
  const listMethod = source.split("listReports", 2)[1].split("getReportDetail", 1)[0];

  assert.match(listMethod, /^\(\{ identity \} = \{\}\)/);
  assert.doesNotMatch(listMethod, /session_id/);
  assert.match(
    listMethod,
    /return getJson\(joinApiPath\(apiBase, "reports\/"\), identity\)/
  );
});
