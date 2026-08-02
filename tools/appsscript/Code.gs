/**
 * ============================================================================
 * Avaya Case Review Suite — Google Apps Script Integration Module
 * ============================================================================
 * Features:
 * 1. Webhooks Endpoint (doPost) for receiving Antigravity case reviews
 * 2. Automated Google Sheets Case Tracking Dashboard generator & updater
 * 3. Executive Google Docs Brief Creator
 * 4. Scheduled Daily/Weekly Manager Email Digest (ScriptApp Triggers)
 * ============================================================================
 */

// Configuration Constants
const CONFIG = {
  SPREADSHEET_ID: "", // Fill in your Google Sheet ID or leave empty to auto-create
  FOLDER_ID: "",      // Optional: Google Drive Folder ID for storing case Doc reports
  NOTIFICATION_EMAIL: "manager-team@avaya.com" // Target email for executive digests
};

/**
 * HTTP POST Webhook Handler
 * Receives JSON payload from Antigravity / Case Review Automation
 */
function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents);
    const result = processCaseReviewPayload(payload);
    
    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      message: "Case review processed successfully",
      data: result
    })).setMimeType(ContentService.MimeType.JSON);
    
  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: error.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * HTTP GET Health Check & Status Endpoint
 */
function doGet(e) {
  return ContentService.createTextOutput(JSON.stringify({
    service: "Avaya Case Review Suite — Apps Script Bridge",
    status: "active",
    timestamp: new Date().toISOString()
  })).setMimeType(ContentService.MimeType.JSON);
}

/**
 * Process Case Review Payload and update Sheet & Doc
 */
function processCaseReviewPayload(data) {
  const caseId = data.case_id || "UNKNOWN";
  const title = data.title || "Untitled Case";
  const healthStatus = data.health_status || "At Risk"; // Healthy, At Risk, Stalled
  const owner = data.owner || "Unassigned";
  const nextOwner = data.next_owner || "Unassigned";
  const summary = data.summary || "";
  const evidence = Array.isArray(data.evidence) ? data.evidence : [];

  // 1. Update Tracking Sheet
  const sheetUrl = updateCaseTrackingSheet({
    caseId, title, healthStatus, owner, nextOwner, summary
  });

  // 2. Generate Google Doc Brief
  const docUrl = createGoogleDocReport({
    caseId, title, healthStatus, owner, nextOwner, summary, evidence
  });

  return {
    caseId: caseId,
    sheetUrl: sheetUrl,
    docUrl: docUrl
  };
}

/**
 * Appends or updates the case entry in a Google Sheet Dashboard
 */
function updateCaseTrackingSheet(caseData) {
  let ss;
  if (CONFIG.SPREADSHEET_ID) {
    ss = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  } else {
    // Check if active spreadsheet or create new
    try {
      ss = SpreadsheetApp.getActiveSpreadsheet();
    } catch(err) {
      ss = SpreadsheetApp.create("Avaya Case Governance Dashboard");
      CONFIG.SPREADSHEET_ID = ss.getId();
    }
  }

  const headers = [
    "Timestamp", "Case ID", "Title", "Health Status", "Current Owner",
    "Next Step Owner", "Summary Verdict"
  ];
  let sheet = ss.getSheetByName("Case Tracker");
  if (!sheet) {
    sheet = ss.insertSheet("Case Tracker");
  } else if (
    sheet.getLastColumn() === 8 &&
    sheet.getRange(1, 8).getValue() === "Summary Verdict"
  ) {
    // Migrate the previous eight-column schema to the current seven columns.
    sheet.deleteColumn(7);
  }
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  sheet.getRange(1, 1, 1, headers.length).setFontWeight("bold").setBackground("#0B192C").setFontColor("#FFFFFF");
  sheet.setFrozenRows(1);

  const timestamp = new Date().toLocaleString("en-US", { timeZone: "America/New_York" });
  const rowData = [
    timestamp,
    caseData.caseId,
    caseData.title,
    caseData.healthStatus,
    caseData.owner,
    caseData.nextOwner,
    caseData.summary
  ];

  sheet.appendRow(rowData);

  // Formatting Status
  const lastRow = sheet.getLastRow();
  const statusCell = sheet.getRange(lastRow, 4);
  if (caseData.healthStatus.toLowerCase().includes("stalled")) {
    statusCell.setBackground("#FEE2E2").setFontColor("#991B1B").setFontWeight("bold");
  } else if (caseData.healthStatus.toLowerCase().includes("risk")) {
    statusCell.setBackground("#FEF3C7").setFontColor("#92400E").setFontWeight("bold");
  } else {
    statusCell.setBackground("#D1FAE5").setFontColor("#065F46").setFontWeight("bold");
  }

  return ss.getUrl();
}

/**
 * Creates an executive Google Doc brief for a case
 */
function createGoogleDocReport(caseData) {
  const docName = `Avaya Case Brief — ${caseData.caseId} (${caseData.healthStatus})`;
  const doc = DocumentApp.create(docName);
  const body = doc.getBody();

  // Header
  const titlePara = body.appendParagraph(`Avaya Case Review Brief: ${caseData.caseId}`);
  titlePara.setHeading(DocumentApp.ParagraphHeading.TITLE);
  titlePara.getRuns()[0].setFontColor("#0B192C");

  // Subtitle / Metadata
  body.appendParagraph(`Title: ${caseData.title}`);
  body.appendParagraph(`Health Verdict: ${caseData.healthStatus}`);
  body.appendParagraph(`Case Owner: ${caseData.owner} | Next Step Owner: ${caseData.nextOwner}`);
  body.appendParagraph(`Generated: ${new Date().toLocaleString()}`);
  body.appendHorizontalRule();

  // Executive Summary
  const h1 = body.appendParagraph("1. Executive Verdict");
  h1.setHeading(DocumentApp.ParagraphHeading.HEADING1);
  body.appendParagraph(caseData.summary);

  // Evidence Appendix
  const h2 = body.appendParagraph("2. Appendix A — Evidence Register");
  h2.setHeading(DocumentApp.ParagraphHeading.HEADING1);
  const tableData = [
    ["Ref", "Date", "Source", "Verbatim evidence / data", "Supports"],
    ...caseData.evidence.map(item => [
      item.ref || "",
      item.date || "not stated",
      item.source || "",
      item.verbatim || "",
      item.supports || ""
    ])
  ];
  const evidenceTable = body.appendTable(tableData);
  const headerRow = evidenceTable.getRow(0);
  for (let i = 0; i < headerRow.getNumCells(); i++) {
    headerRow.getCell(i).setBackgroundColor("#0B192C");
    headerRow.getCell(i).editAsText().setForegroundColor("#FFFFFF").setBold(true);
  }

  doc.saveAndClose();

  // Move to folder if configured
  if (CONFIG.FOLDER_ID) {
    const file = DriveApp.getFileById(doc.getId());
    const folder = DriveApp.getFolderById(CONFIG.FOLDER_ID);
    file.moveTo(folder);
  }

  return doc.getUrl();
}

/**
 * Scheduled Trigger Function: Sends Daily Stalled Cases Digest to Managers
 * Can be configured via Apps Script Triggers (e.g. daily at 8:00 AM)
 */
function sendDailyManagerDigest() {
  if (!CONFIG.SPREADSHEET_ID) return;
  const ss = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  const sheet = ss.getSheetByName("Case Tracker");
  if (!sheet) return;

  const data = sheet.getDataRange().getValues();
  if (data.length <= 1) return;

  let stalledCount = 0;
  let riskCount = 0;
  let rowsHtml = "";

  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    const caseId = row[1];
    const title = row[2];
    const status = row[3];
    const owner = row[4];
    const nextOwner = row[5];

    if (status.toLowerCase().includes("stalled") || status.toLowerCase().includes("risk")) {
      if (status.toLowerCase().includes("stalled")) stalledCount++;
      if (status.toLowerCase().includes("risk")) riskCount++;

      rowsHtml += `
        <tr>
          <td style="padding: 8px; border: 1px solid #ccc;"><b>${caseId}</b></td>
          <td style="padding: 8px; border: 1px solid #ccc;">${title}</td>
          <td style="padding: 8px; border: 1px solid #ccc; color: ${status.toLowerCase().includes("stalled") ? "red" : "orange"};"><b>${status}</b></td>
          <td style="padding: 8px; border: 1px solid #ccc;">${owner}</td>
          <td style="padding: 8px; border: 1px solid #ccc;">${nextOwner}</td>
        </tr>
      `;
    }
  }

  if (stalledCount > 0 || riskCount > 0) {
    const htmlBody = `
      <h2>Avaya Operations Manager Daily Stalled Case Alert</h2>
      <p>The case tracker contains <b>${stalledCount} Stalled</b> and <b>${riskCount} At Risk</b> cases for manager review.</p>
      <table style="border-collapse: collapse; width: 100%;">
        <thead>
          <tr style="background-color: #0B192C; color: white;">
            <th style="padding: 8px; border: 1px solid #ccc;">Case ID</th>
            <th style="padding: 8px; border: 1px solid #ccc;">Title</th>
            <th style="padding: 8px; border: 1px solid #ccc;">Status</th>
            <th style="padding: 8px; border: 1px solid #ccc;">Owner</th>
            <th style="padding: 8px; border: 1px solid #ccc;">Next Owner</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>
      <p><a href="${ss.getUrl()}">View Full Governance Dashboard Sheet</a></p>
    `;

    MailApp.sendEmail({
      to: CONFIG.NOTIFICATION_EMAIL,
      subject: `[CASE REVIEW] ${stalledCount} Stalled / ${riskCount} At-Risk Cases`,
      htmlBody: htmlBody
    });
  }
}
