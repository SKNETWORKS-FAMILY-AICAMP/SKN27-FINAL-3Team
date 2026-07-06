export function createFrontendApi({ apiBase = "/api" } = {}) {
  const authApiBase = toCanonicalApiBase(apiBase);

  return {
    authApiBase,
    apiBase,
    createGuestSession(payload = {}) {
      return postJson(joinApiPath(authApiBase, "auth/guest-session/"), payload);
    },
    loginWithGoogle(payload = {}) {
      return postJson(joinApiPath(authApiBase, "auth/login/"), {
        provider: "google",
        ...payload,
      });
    },
    loginWithGoogleCode(payload = {}) {
      return postJson(
        joinApiPath(authApiBase, "auth/google/code/"),
        {
          provider: "google",
          ...payload,
        },
        {},
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
    processAgentWorkItems(payload = {}, identity = {}) {
      return postJson(joinApiPath(apiBase, "agents/work-items/process/"), payload, identity);
    },
    getAnalysisJobDetail({ jobId, identity } = {}) {
      return getJson(joinApiPath(apiBase, `analysis/jobs/${encodeURIComponent(jobId || "")}/`), identity);
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
    processFileScan({ attachmentId, ...payload } = {}, identity = {}) {
      return postJson(joinApiPath(apiBase, `files/${encodeURIComponent(attachmentId || "")}/scan/`), payload, identity);
    },
    updateConversationSaveState(payload = {}, identity = {}) {
      return postJson(joinApiPath(apiBase, "chat/save-state/"), payload, identity);
    },
    runReportAction(payload = {}, identity = {}) {
      return postJson(joinApiPath(apiBase, "reports/"), payload, identity);
    },
    downloadReport({ reportId, sessionId, identity } = {}) {
      const url = withQuery(joinApiPath(apiBase, `reports/${encodeURIComponent(reportId || "")}/download/`), {
        session_id: sessionId,
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
  { authToken, guestId, authSessionId } = {},
  { includeContentType = false } = {}
) {
  return {
    ...(includeContentType ? { "Content-Type": "application/json" } : {}),
    ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    ...(guestId ? { "X-Guest-Id": guestId } : {}),
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
  const normalized = trimTrailingSlash(apiBase);
  return normalized.endsWith("/mock") ? normalized.slice(0, -"/mock".length) : normalized;
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
    throw new Error(`Request failed: ${response.status}${reason ? ` ${reason}` : ""}`);
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
