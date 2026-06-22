import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const outputDir = "D:/dev/Project/SKN27-FINAL-3Team/tmp/pdf_wbs_req/template_previews";
await fs.mkdir(outputDir, { recursive: true });

const templates = [
  {
    key: "requirements",
    path: "C:/Users/Playdata/Downloads/[모델배포]_요구사항 정의서_양식_27기_0팀.xlsx의 사본",
  },
  {
    key: "wbs",
    path: "C:/Users/Playdata/Downloads/[기획] WBS_양식 (1)_27기_0팀.xlsx",
  },
];

const summaries = [];

for (const template of templates) {
  const input = await FileBlob.load(template.path);
  const workbook = await SpreadsheetFile.importXlsx(input);
  const summary = await workbook.inspect({
    kind: "workbook,sheet,table,region,computedStyle",
    maxChars: 12000,
    tableMaxRows: 12,
    tableMaxCols: 20,
    tableMaxCellChars: 120,
  });
  summaries.push({ key: template.key, ndjson: summary.ndjson });

  const sheets = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 4000 });
  const sheetLines = sheets.ndjson.trim().split(/\n+/).filter(Boolean).map((line) => JSON.parse(line));
  for (const sheet of sheetLines) {
    const sheetName = sheet.name ?? sheet.id;
    const safeSheetName = String(sheetName).replace(/[^\w가-힣.-]+/g, "_");
    const preview = await workbook.render({
      sheetName,
      autoCrop: "all",
      scale: 1,
      format: "png",
    });
    await fs.writeFile(
      path.join(outputDir, `${template.key}_${safeSheetName}.png`),
      new Uint8Array(await preview.arrayBuffer()),
    );
  }
}

await fs.writeFile(
  "D:/dev/Project/SKN27-FINAL-3Team/tmp/pdf_wbs_req/template_inspect.ndjson",
  summaries.map((item) => JSON.stringify(item)).join("\n"),
  "utf8",
);

console.log(JSON.stringify({ outputDir, summaries: summaries.length }, null, 2));
