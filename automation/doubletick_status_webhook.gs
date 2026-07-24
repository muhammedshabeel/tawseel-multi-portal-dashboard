const PORTALS = [
  {
    name: 'Emarath.com',
    sheetId: '1IVB3AHxVQ-e5cdfuhY_ivn_jzo98zH5Oim32E9hkAmU'
  },
  {
    name: 'Oud Al Salam',
    sheetId: '1mZ9vk4MONgCptwaBQT85xptPNqc6-H8Tek10hNAOL08'
  },
  {
    name: 'Scent Passion',
    sheetId: '1CffTs_YF2JFUVvT3-SLEWmdtDVz0J4bsYDzpk67Ryng'
  }
];

const REPORT_TAB = 'DoubleTick_Notifications';
const ALLOWED_STATUSES = new Set(['SENT', 'DELIVERED', 'READ', 'FAILED']);
const STATUS_RANK = {
  API_ACCEPTED: 0,
  SENT: 1,
  DELIVERED: 2,
  READ: 3,
  FAILED: 4
};

function doPost(e) {
  try {
    const payload = JSON.parse((e.postData && e.postData.contents) || '{}');
    const status = String(payload.status || '').trim().toUpperCase();
    const phone = normalizePhone(payload.to || '');
    const messageId = String(payload.messageId || '').trim();
    const statusTimestamp = String(
      payload.statusTimestamp || payload.statusTimeStamp || new Date().toISOString()
    ).trim();
    const failMessage = String(payload.failMessage || '').trim();
    const wabaNumber = normalizePhone(payload.wabaNumber || '');

    if (!ALLOWED_STATUSES.has(status)) {
      return jsonResponse({ ok: true, ignored: true, reason: 'Unsupported status' });
    }

    if (!phone) {
      return jsonResponse({ ok: false, error: 'Missing customer phone' }, 400);
    }

    let updated = 0;
    const updates = [];

    PORTALS.forEach((portal) => {
      const result = updatePortalSheet(
        portal,
        phone,
        messageId,
        status,
        statusTimestamp,
        failMessage,
        wabaNumber
      );

      updated += result.updated;
      updates.push(result);
    });

    return jsonResponse({
      ok: true,
      status,
      phone,
      messageId,
      updated,
      portals: updates
    });
  } catch (error) {
    console.error(error);
    return jsonResponse({ ok: false, error: String(error) }, 500);
  }
}

function doGet() {
  return jsonResponse({
    ok: true,
    service: 'DoubleTick Message Status Webhook',
    timestamp: new Date().toISOString()
  });
}

function updatePortalSheet(
  portal,
  phone,
  messageId,
  newStatus,
  statusTimestamp,
  failMessage,
  wabaNumber
) {
  try {
    const spreadsheet = SpreadsheetApp.openById(portal.sheetId);
    const sheet = spreadsheet.getSheetByName(REPORT_TAB);

    if (!sheet) {
      return { portal: portal.name, updated: 0, reason: 'Report tab not found' };
    }

    const values = sheet.getDataRange().getValues();

    if (values.length < 2) {
      return { portal: portal.name, updated: 0, reason: 'No report rows' };
    }

    const headers = buildHeaderMap(values[0]);
    const required = [
      'PHONE',
      'TEMPLATE RESULT',
      'TEMPLATE MESSAGE ID',
      'ERROR',
      'TIMESTAMP'
    ];

    const missing = required.filter((header) => !headers[header]);

    if (missing.length) {
      return {
        portal: portal.name,
        updated: 0,
        reason: `Missing columns: ${missing.join(', ')}`
      };
    }

    const phoneColumn = headers.PHONE;
    const resultColumn = headers['TEMPLATE RESULT'];
    const messageIdColumn = headers['TEMPLATE MESSAGE ID'];
    const errorColumn = headers.ERROR;
    const timestampColumn = headers.TIMESTAMP;
    const webhookTimeColumn = ensureColumn(sheet, headers, 'Webhook Status Time');
    const wabaColumn = ensureColumn(sheet, headers, 'Webhook WABA');

    let targetRow = -1;

    for (let rowIndex = 1; rowIndex < values.length; rowIndex += 1) {
      const row = values[rowIndex];
      const rowPhone = normalizePhone(row[phoneColumn - 1]);
      const rowMessageId = String(row[messageIdColumn - 1] || '').trim();

      if (messageId && rowMessageId && rowMessageId === messageId) {
        targetRow = rowIndex + 1;
        break;
      }

      if (rowPhone === phone) {
        targetRow = rowIndex + 1;
      }
    }

    if (targetRow < 0) {
      return { portal: portal.name, updated: 0, reason: 'No matching phone/messageId' };
    }

    const currentStatus = String(
      sheet.getRange(targetRow, resultColumn).getValue() || ''
    ).trim().toUpperCase();

    if (!shouldApplyStatus(currentStatus, newStatus)) {
      return {
        portal: portal.name,
        updated: 0,
        reason: `Ignored regression ${currentStatus} -> ${newStatus}`
      };
    }

    const timestamp = parseStatusTimestamp(statusTimestamp);
    const errorValue = newStatus === 'FAILED' ? failMessage : '';

    const updateRanges = [
      sheet.getRange(targetRow, resultColumn),
      sheet.getRange(targetRow, timestampColumn),
      sheet.getRange(targetRow, webhookTimeColumn),
      sheet.getRange(targetRow, wabaColumn)
    ];

    updateRanges[0].setValue(newStatus);
    updateRanges[1].setValue(timestamp);
    updateRanges[2].setValue(timestamp);
    updateRanges[3].setValue(wabaNumber);

    if (messageId) {
      sheet.getRange(targetRow, messageIdColumn).setValue(messageId);
    }

    sheet.getRange(targetRow, errorColumn).setValue(errorValue);

    return { portal: portal.name, updated: 1, row: targetRow, status: newStatus };
  } catch (error) {
    console.error(`${portal.name}: ${error}`);
    return { portal: portal.name, updated: 0, reason: String(error) };
  }
}

function shouldApplyStatus(currentStatus, newStatus) {
  if (newStatus === 'FAILED') {
    return true;
  }

  if (currentStatus === 'FAILED') {
    return false;
  }

  const currentRank = STATUS_RANK[currentStatus] ?? -1;
  const newRank = STATUS_RANK[newStatus] ?? -1;
  return newRank >= currentRank;
}

function ensureColumn(sheet, headers, headerName) {
  const normalized = normalizeHeader(headerName);

  if (headers[normalized]) {
    return headers[normalized];
  }

  const nextColumn = sheet.getLastColumn() + 1;
  sheet.getRange(1, nextColumn).setValue(headerName);
  headers[normalized] = nextColumn;
  return nextColumn;
}

function buildHeaderMap(headers) {
  const map = {};
  headers.forEach((header, index) => {
    const normalized = normalizeHeader(header);
    if (normalized) {
      map[normalized] = index + 1;
    }
  });
  return map;
}

function normalizeHeader(value) {
  return String(value || '').trim().replace(/\s+/g, ' ').toUpperCase();
}

function normalizePhone(value) {
  let phone = String(value || '').replace(/\D/g, '');

  if (phone.startsWith('00')) {
    phone = phone.substring(2);
  }

  if (phone.startsWith('0') && phone.length === 10) {
    phone = `971${phone.substring(1)}`;
  } else if (phone.startsWith('5') && phone.length === 9) {
    phone = `971${phone}`;
  }

  return phone;
}

function parseStatusTimestamp(value) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
}

function jsonResponse(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
