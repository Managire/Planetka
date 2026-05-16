export const PLAN_CODE_FREE = "free";

const DEFAULT_DEVICE_LIMIT_EXEMPT_EMAILS = "tom.griger@gmail.com";

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

export function normalizeUserStatus(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === PLAN_CODE_FREE) {
    return PLAN_CODE_FREE;
  }
  return normalized;
}

export function normalizePlanCode(value) {
  return normalizeUserStatus(value);
}

export function parseCsvEmailSet(value, fallback = "") {
  const set = new Set();
  const source = String(value || fallback || "").trim();
  if (!source) {
    return set;
  }
  for (const token of source.split(",")) {
    const email = normalizeEmail(token);
    if (email && email.includes("@")) {
      set.add(email);
    }
  }
  return set;
}

export function isDeviceLimitExemptEmail(email, env = {}) {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail) {
    return false;
  }
  const set = parseCsvEmailSet(env.DEVICE_LIMIT_EXEMPT_EMAILS, DEFAULT_DEVICE_LIMIT_EXEMPT_EMAILS);
  return set.has(normalizedEmail);
}

export function isBlockedStatus(statusValue) {
  return String(statusValue || "").trim().toLowerCase() === "blocked";
}

export function normalizeRequestedPlan(value) {
  const normalized = normalizePlanCode(value);
  return normalized === PLAN_CODE_FREE ? PLAN_CODE_FREE : PLAN_CODE_FREE;
}

export function resolvePolicyPlanCode(user, env = {}) {
  void env;
  if (user && isBlockedStatus(user.status)) {
    return "blocked";
  }
  return normalizeRequestedPlan(user && user.status);
}

export function resolvePlanCode(user, env = {}) {
  const resolved = resolvePolicyPlanCode(user, env);
  if (resolved === "blocked") {
    return resolved;
  }
  return normalizeRequestedPlan(resolved);
}

export function normalizeQualityMode(value) {
  const safe = String(value || "").trim().toLowerCase();
  if (safe === "full") return "full";
  return "preview";
}

export function isQualityModeAllowedForPlan(planCode, qualityMode) {
  void planCode;
  const safeMode = normalizeQualityMode(qualityMode);
  return safeMode === "preview" || safeMode === "full";
}

export function qualityModeNotAllowedMessage(planCode, qualityMode) {
  void planCode;
  const safeMode = normalizeQualityMode(qualityMode);
  if (safeMode === "preview") {
    return "Preview quality is free.";
  }
  return "Full Quality requires direct payment.";
}

export function accountTierForPlanCode(planCode) {
  return normalizeRequestedPlan(planCode);
}

export function planDisplayName(planCode) {
  void planCode;
  return "Free";
}

export function planAccessSummary(planCode) {
  void planCode;
  return "Preview is free. Full Quality is licenced through direct payment.";
}

export function resolvePlanPriority(planCode) {
  void planCode;
  return 0;
}

export function evaluateStripePlanPurchaseGuard(existingPlanCode, requestedPlanCode) {
  const existing = normalizeRequestedPlan(existingPlanCode);
  const requested = normalizeRequestedPlan(requestedPlanCode);
  return {
    blocked: false,
    reason: "",
    existingPlanCode: existing,
    requestedPlanCode: requested,
  };
}
