import caseApiRoutes from "./caseApiRoutes.json";

export function createFrontendApi({ apiBase = "/api" } = {}) {
  const authApiBase = toCanonicalApiBase(apiBase);

  return {
    authApiBase,
    apiBase,
    createGuestSession(payload = {}, identity = {}) {
      return postJson(joinApiPath(authApiBase, "auth/guest-session/"), payload, identity);
    },
    loginWithGoogleCode(payload = {}, identity = {}) {
      return postJson(
        joinApiPath(authApiBase, "auth/google/code/"),
        {
          provider: "google",
          ...payload,
        },
        identity,
        { extraHeaders: { "X-Requested-With": "XmlHttpRequest" } }
      );
    },
    getCurrentAuthSubject({ sessionId, identity } = {}) {
      return getJson(buildAuthMeUrl(authApiBase, sessionId), identity);
    },
    refreshAuthToken(payload = {}, identity = {}) {
      return postJson(joinApiPath(authApiBase, "auth/refresh/"), payload, identity);
    },
    logoutAuthSession(payload = {}, identity = {}) {
      return postJson(joinApiPath(authApiBase, "auth/logout/"), payload, identity);
    },
    submitChatMessage(payload = {}, identity = {}) {
      return postJson(joinApiPath(apiBase, "chat/messages/"), payload, identity);
    },
    getCapabilities() {
      return getJson(joinApiPath(apiBase, "capabilities/"));
    },
    getAnalysisJobDetail({ jobId, identity } = {}) {
      return getJson(joinApiPath(apiBase, `analysis/jobs/${encodeURIComponent(jobId || "")}/`), identity);
    },
    getAnalysisResult({ jobId, identity } = {}) {
      return getJson(joinApiPath(apiBase, `analysis/results/${encodeURIComponent(jobId || "")}/`), identity);
    },
    registerFileMetadata(payload = {}, identity = {}) {
      return postJson(joinApiPath(apiBase, "files/"), payload, identity);
    },
    uploadFile({ file, ...payload } = {}, identity = {}) {
      const formData = new FormData();
      Object.entries(payload || {}).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
          formData.append(key, value);
        }
      });
      if (file) {
        formData.append("file", file);
      }
      return postFormData(joinApiPath(apiBase, "files/"), formData, identity);
    },
    updateConversationSaveState(payload = {}, identity = {}) {
      return postJson(joinApiPath(apiBase, "chat/save-state/"), payload, identity);
    },
    listConsultationCases({ identity } = {}) {
      return requestCaseApi(apiBase, "listConsultationCases", { identity });
    },
    createConsultationCase(payload = {}, identity = {}) {
      return requestCaseApi(apiBase, "createConsultationCase", { payload, identity });
    },
    getConsultationCaseWorkspace({ caseId, identity } = {}) {
      return requestCaseApi(apiBase, "getConsultationCaseWorkspace", { caseId, identity });
    },
    confirmConsultationCaseFacts({ caseId, payload = {}, identity } = {}) {
      return requestCaseApi(apiBase, "confirmConsultationCaseFacts", {
        caseId,
        payload,
        identity,
      });
    },
    startConsultationCaseAnalysis({ caseId, payload = {}, identity } = {}) {
      return requestCaseApi(apiBase, "startConsultationCaseAnalysis", {
        caseId,
        payload,
        identity,
      });
    },
    runReportAction(payload = {}, identity = {}) {
      return postJson(joinApiPath(apiBase, "reports/"), payload, identity);
    },
    listReports({ sessionId, identity } = {}) {
      const url = withQuery(joinApiPath(apiBase, "reports/"), { session_id: sessionId });
      return getJson(url, identity);
    },
    getReportDetail({ reportId, sessionId, identity } = {}) {
      const url = withQuery(joinApiPath(apiBase, `reports/${encodeURIComponent(reportId || "")}/`), {
        session_id: sessionId,
      });
      return getJson(url, identity);
    },
    confirmReportDocument({ reportId, sessionId, identity, confirmation } = {}) {
      const url = withQuery(
        joinApiPath(apiBase, `reports/${encodeURIComponent(reportId || "")}/document-confirmation/`),
        { session_id: sessionId }
      );
      return postJson(url, confirmation, identity);
    },
    downloadReport({ reportId, sessionId, identity, documentType } = {}) {
      const url = withQuery(joinApiPath(apiBase, `reports/${encodeURIComponent(reportId || "")}/download/`), {
        session_id: sessionId,
        document_type: documentType,
      });
      return getBlob(url, identity);
    },
    getMyPageSummary({ sessionId, identity } = {}) {
      const url = withQuery(joinApiPath(apiBase, "mypage/summary/"), { session_id: sessionId });
      return getJson(url, identity);
    },
    listHistoryEvents({ sessionId, jobId, identity } = {}) {
      const url = withQuery(joinApiPath(apiBase, "history/"), {
        session_id: sessionId,
        job_id: jobId,
      });
      return getJson(url, identity);
    },
  };
}

function requestCaseApi(
  apiBase,
  operationId,
  { caseId, payload = {}, identity = {} } = {}
) {
  const route = caseApiRoutes[operationId];
  if (!route) {
    throw new Error(`Unknown Case API operation: ${operationId}`);
  }

  const path = route.path.replace("{case_id}", encodeURIComponent(caseId || ""));
  const url = joinApiPath(apiBase, path);
  if (route.method === "GET") {
    return getJson(url, identity);
  }
  if (route.method === "POST") {
    return postJson(url, payload, identity);
  }
  throw new Error(`Unsupported Case API method: ${route.method}`);
}

export async function postJson(url, payload, identity = {}, options = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      ...buildRequestHeaders(identity, { includeContentType: true }),
      ...(options.extraHeaders || {}),
    },
    body: JSON.stringify(payload || {}),
  });

  return parseJsonResponse(response);
}

export async function postFormData(url, formData, identity = {}, options = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      ...buildRequestHeaders(identity),
      ...(options.extraHeaders || {}),
    },
    body: formData,
  });

  return parseJsonResponse(response);
}

export async function getJson(url, identity = {}) {
  const response = await fetch(url, {
    method: "GET",
    headers: buildRequestHeaders(identity),
  });

  return parseJsonResponse(response);
}

export async function getBlob(url, identity = {}) {
  const response = await fetch(url, {
    method: "GET",
    headers: buildRequestHeaders(identity),
  });

  if (!response.ok) {
    await parseJsonResponse(response);
  }

  return {
    blob: await response.blob(),
    contentType: response.headers.get("Content-Type") || "application/octet-stream",
    filename: filenameFromContentDisposition(response.headers.get("Content-Disposition")),
  };
}

export function buildRequestHeaders(
  { authToken, guestId, guestCredential, authSessionId } = {},
  { includeContentType = false } = {}
) {
  return {
    ...(includeContentType ? { "Content-Type": "application/json" } : {}),
    ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    ...(guestId ? { "X-Guest-Id": guestId } : {}),
    ...(guestCredential ? { "X-Guest-Credential": guestCredential } : {}),
    ...(authSessionId ? { "X-Auth-Session-Id": authSessionId } : {}),
  };
}

export function buildAuthMeUrl(apiBase, sessionId) {
  const url = joinApiPath(apiBase, "auth/me/");
  if (!sessionId) {
    return url;
  }
  return withQuery(url, { session_id: sessionId });
}

export function joinApiPath(apiBase, path) {
  return `${trimTrailingSlash(apiBase)}/${String(path || "").replace(/^\/+/, "")}`;
}

export function toCanonicalApiBase(apiBase) {
  return trimTrailingSlash(apiBase);
}

export function withQuery(url, params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, value);
    }
  });
  const queryString = query.toString();
  return queryString ? `${url}?${queryString}` : url;
}

async function parseJsonResponse(response) {
  let payload = null;
  try {
    payload = await response.clone().json();
  } catch (_error) {
    payload = null;
  }

  if (!response.ok) {
    const error = payload?.error || {};
    const reason = error?.auth?.reason || error?.reason || error?.code || response.statusText;
    const publicMessage = typeof error?.message === "string" ? error.message.trim() : "";
    const requestError = new Error(`Request failed: ${response.status}${reason ? ` ${reason}` : ""}`);
    requestError.status = response.status;
    requestError.code = error?.code || null;
    requestError.reason = reason || null;
    requestError.requiredAction = error?.required_action || null;
    requestError.payload = payload;
    requestError.publicMessage = publicMessage;
    throw requestError;
  }
  return payload ?? response.json();
}

function filenameFromContentDisposition(value) {
  const header = String(value || "");
  const encoded = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (encoded?.[1]) {
    try {
      return decodeURIComponent(encoded[1].replace(/"/g, ""));
    } catch (_error) {
      return encoded[1].replace(/"/g, "");
    }
  }
  const plain = header.match(/filename="?([^";]+)"?/i);
  return plain?.[1] || "";
}

function trimTrailingSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}
