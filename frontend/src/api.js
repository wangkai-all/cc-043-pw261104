export const API = "";

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = payload?.detail;
    const error = new Error(
      typeof detail === "string" ? detail : detail?.reasons?.join("；") || "请求失败",
    );
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

export const api = {
  health: () => request("/api/health"),
  scenarios: () => request("/api/demo/scenarios"),
  contracts: () => request("/api/contracts"),
  contract: (no) => request(`/api/contracts/${encodeURIComponent(no)}`),
  timeline: (no, params) =>
    request(
      `/api/contracts/${encodeURIComponent(no)}/timeline?${new URLSearchParams(params)}`,
    ),
  view: (no, businessAt, asOf) =>
    request(
      `/api/contracts/${encodeURIComponent(no)}/view?${new URLSearchParams({
        business_at: businessAt,
        as_of: asOf,
      })}`,
    ),
  create: (body) =>
    request("/api/contracts", { method: "POST", body: JSON.stringify(body) }),
  correct: (no, body) =>
    request(`/api/contracts/${encodeURIComponent(no)}/corrections`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  resetDemo: () => request("/api/demo/reset", { method: "POST" }),
  conflictDrill: (body) =>
    request("/api/demo/conflict", { method: "POST", body: JSON.stringify(body) }),
};
