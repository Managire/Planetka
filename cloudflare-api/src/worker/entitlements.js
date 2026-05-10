export const PLAN_CODE_FREE = "free";
export const PLAN_CODE_PERSONAL = "personal";
export const PLAN_CODE_COMMERCIAL = "commercial";

const DEFAULT_DEVICE_LIMIT_EXEMPT_EMAILS = "tom.griger@gmail.com";

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

export function normalizeUserStatus(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === PLAN_CODE_COMMERCIAL) {
    return PLAN_CODE_COMMERCIAL;
  }
  if (normalized === PLAN_CODE_PERSONAL) {
    return PLAN_CODE_PERSONAL;
  }
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
  if (normalized === PLAN_CODE_COMMERCIAL) {
    return PLAN_CODE_COMMERCIAL;
  }
  if (normalized === PLAN_CODE_PERSONAL) {
    return PLAN_CODE_PERSONAL;
  }
  return PLAN_CODE_FREE;
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
  if (safe === "balanced") return "balanced";
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
  if (safeMode === "balanced") {
    return "Only Preview and Full Quality are available.";
  }
  return "Full Quality requires direct payment.";
}

export function commercialUseAllowed(planCode) {
  return normalizeRequestedPlan(planCode) === PLAN_CODE_COMMERCIAL;
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
  const normalized = normalizeRequestedPlan(planCode);
  if (normalized === PLAN_CODE_COMMERCIAL) {
    return 2;
  }
  if (normalized === PLAN_CODE_PERSONAL) {
    return 1;
  }
  return 0;
}

export function evaluateStripePlanPurchaseGuard(existingPlanCode, requestedPlanCode) {
  const existing = normalizeRequestedPlan(existingPlanCode);
  const requested = normalizeRequestedPlan(requestedPlanCode);
  const existingPriority = resolvePlanPriority(existing);
  const requestedPriority = resolvePlanPriority(requested);
  if (existingPriority <= 0 || requestedPriority <= 0) {
    return {
      blocked: false,
      reason: "",
      existingPlanCode: existing,
      requestedPlanCode: requested,
    };
  }
  if (existingPriority < requestedPriority) {
    return {
      blocked: false,
      reason: "",
      existingPlanCode: existing,
      requestedPlanCode: requested,
    };
  }
  const reason = existingPriority === requestedPriority
    ? "already_has_licence"
    : "higher_tier_already_active";
  return {
    blocked: true,
    reason,
    existingPlanCode: existing,
    requestedPlanCode: requested,
  };
}
