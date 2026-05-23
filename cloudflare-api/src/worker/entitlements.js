export const PLAN_CODE_FREE = "free";
export const PLAN_CODE_PROFESSIONAL = "pro";

const DEFAULT_DEVICE_LIMIT_EXEMPT_EMAILS = "tom.griger@gmail.com";

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

export function normalizeUserStatus(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["professional", "pro", "paid", "unlimited"].includes(normalized)) {
    return PLAN_CODE_PROFESSIONAL;
  }
  if (["personal", PLAN_CODE_FREE, ""].includes(normalized)) {
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
  if (normalized === PLAN_CODE_PROFESSIONAL) return PLAN_CODE_PROFESSIONAL;
  return PLAN_CODE_FREE;
}

export function betaProAccountsEnabled(env = {}) {
  const raw = String(
    env.PLANETKA_BETA_DEFAULT_PRO
    ?? env.BETA_DEFAULT_PRO
    ?? env.BETA_PRO_ACCOUNTS
    ?? "1",
  ).trim().toLowerCase();
  return !["0", "false", "off", "no"].includes(raw);
}

export function defaultSignupPlanCode(env = {}) {
  return betaProAccountsEnabled(env) ? PLAN_CODE_PROFESSIONAL : PLAN_CODE_FREE;
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
  const plan = normalizeRequestedPlan(planCode);
  const quality = normalizeQualityMode(qualityMode);
  if (plan === PLAN_CODE_PROFESSIONAL) return true;
  return quality === "preview" || quality === "balanced";
}

export function qualityModeNotAllowedMessage(planCode, qualityMode) {
  const plan = normalizeRequestedPlan(planCode);
  const quality = normalizeQualityMode(qualityMode);
  if (plan === PLAN_CODE_FREE && quality === "full") {
    return "Full texture quality requires a Pro account.";
  }
  return "Selected texture quality is not available for this account.";
}

function parseS2TextureTier(fileName) {
  const match = /^S2_x\d+_y\d+_z(\d+)_d(\d+)\.exr$/i.exec(String(fileName || "").trim());
  if (!match) return null;
  return {
    z: Number.parseInt(match[1], 10),
    d: Number.parseInt(match[2], 10),
  };
}

export function isTileFileAllowedForPlan(planCode, fileName) {
  const tier = parseS2TextureTier(fileName);
  if (!tier) return true;
  const plan = normalizeRequestedPlan(planCode);
  if (plan === PLAN_CODE_PROFESSIONAL) return true;
  return !(tier.z === 1 && tier.d === 1);
}

export function tileFileNotAllowedMessage(planCode, fileName) {
  const tier = parseS2TextureTier(fileName);
  const plan = normalizeRequestedPlan(planCode);
  if (plan === PLAN_CODE_FREE && tier && tier.z === 1 && tier.d === 1) {
    return "Full texture quality requires a Pro account.";
  }
  return "This texture file is not available for this account.";
}

export function isProfessionalPlan(planCode) {
  return normalizeRequestedPlan(planCode) === PLAN_CODE_PROFESSIONAL;
}

export function accountTierForPlanCode(planCode) {
  return normalizeRequestedPlan(planCode);
}

export function planDisplayName(planCode) {
  const plan = normalizeRequestedPlan(planCode);
  if (plan === PLAN_CODE_PROFESSIONAL) return "Pro";
  return "Free";
}

export function planAccessSummary(planCode) {
  const plan = normalizeRequestedPlan(planCode);
  if (plan === PLAN_CODE_PROFESSIONAL) {
    return "Pro account: Preview, Balanced, and Full texture quality streaming with commercial licence.";
  }
  return "Free account: Preview and Balanced texture quality streaming for personal use.";
}

export function resolvePlanPriority(planCode) {
  const plan = normalizeRequestedPlan(planCode);
  if (plan === PLAN_CODE_PROFESSIONAL) return 20;
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
