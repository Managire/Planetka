export const PLAN_CODE_PERSONAL = "personal";
export const PLAN_CODE_COMMERCIAL = "commercial";

const DEFAULT_DEVICE_LIMIT_EXEMPT_EMAILS = "tom.griger@gmail.com";

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

export function normalizeUserStatus(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "blocked") {
    return "blocked";
  }
  if (["commercial", "paid", "unlimited", "personal", ""].includes(normalized)) {
    return PLAN_CODE_COMMERCIAL;
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
  if (normalized === "blocked") return "blocked";
  return PLAN_CODE_COMMERCIAL;
}

export function defaultSignupPlanCode(env = {}) {
  void env;
  return PLAN_CODE_COMMERCIAL;
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
  void qualityMode;
  return true;
}

export function qualityModeNotAllowedMessage(planCode, qualityMode) {
  void planCode;
  void qualityMode;
  return "Selected texture quality is not available.";
}

function parseS2TextureTier(fileName) {
  const match = /^S2_x\d+_y\d+_z(\d+)_d(\d+)\.exr$/i.exec(String(fileName || "").trim());
  if (!match) return null;
  return {
    z: Number.parseInt(match[1], 10),
    d: Number.parseInt(match[2], 10),
  };
}

function parseCloudDLevel(fileName) {
  const safeName = String(fileName || "").trim();
  if (/^cloud\d+_vox\d+_(?:60|90|120|150)\.vdb$/i.test(safeName)) {
    return 1;
  }
  const match = /(?:^|_)d(\d+)\.(?:exr|vdb)$/i.exec(safeName);
  if (!match) return null;
  return Number.parseInt(match[1], 10);
}

export function isTileFileAllowedForPlan(planCode, fileName) {
  void planCode;
  void fileName;
  return true;
}

export function tileFileNotAllowedMessage(planCode, fileName) {
  void planCode;
  void fileName;
  return "This texture file is not available.";
}

export function isCommercialPlan(planCode) {
  return normalizeRequestedPlan(planCode) === PLAN_CODE_COMMERCIAL;
}

export function accountLicenceForPlanCode(planCode) {
  return normalizeRequestedPlan(planCode);
}

export function planDisplayName(planCode) {
  const plan = normalizeRequestedPlan(planCode);
  if (plan === "blocked") return "Blocked";
  if (plan === PLAN_CODE_COMMERCIAL) return "Commercial";
  return "Personal";
}

export function planAccessSummary(planCode) {
  const plan = normalizeRequestedPlan(planCode);
  if (plan === "blocked") {
    return "Blocked account.";
  }
  if (plan === PLAN_CODE_COMMERCIAL) {
    return "Commercial licence: all Planetka features for commercial and personal use.";
  }
  return "Personal licence: all Planetka features for personal use only.";
}

export function resolvePlanPriority(planCode) {
  const plan = normalizeRequestedPlan(planCode);
  if (plan === "blocked") return -1;
  if (plan === PLAN_CODE_COMMERCIAL) return 20;
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
