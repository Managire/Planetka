import { isBetaUnrestrictedAccessEnabled } from "./env.js";

export const PLAN_CODE_PLANETKA_FREE = "free";
export const PLAN_CODE_PLANETKA = "lite";
export const PLAN_CODE_PLANETKA_PRO = "pro";
export const PLAN_CODE_PLANETKA_INDIE = PLAN_CODE_PLANETKA;
export const PLAN_CODE_PLANETKA_STUDIO = PLAN_CODE_PLANETKA_PRO;

const DEFAULT_PERMANENT_PRO_EMAILS = "";
const DEFAULT_DEVICE_LIMIT_EXEMPT_EMAILS = "tom.griger@gmail.com";

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

export function normalizeUserStatus(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (
    normalized === PLAN_CODE_PLANETKA_PRO
    || normalized === "pro"
    || normalized === "planetka_pro"
    || normalized === "planetka_studio"
    || normalized === "studio"
  ) {
    return PLAN_CODE_PLANETKA_PRO;
  }
  if (normalized === PLAN_CODE_PLANETKA_INDIE || normalized === "indie") {
    return PLAN_CODE_PLANETKA;
  }
  if (
    normalized === PLAN_CODE_PLANETKA
    || normalized === "planetka"
    || normalized === "personal"
    || normalized === "basic"
    || normalized === "lite"
  ) {
    return PLAN_CODE_PLANETKA;
  }
  if (normalized === PLAN_CODE_PLANETKA_FREE || normalized === "free" || normalized === "trial") {
    return PLAN_CODE_PLANETKA_FREE;
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

export function isPermanentProEmail(email, env = {}) {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail) {
    return false;
  }
  const set = parseCsvEmailSet(env.PERMANENT_PRO_EMAILS, DEFAULT_PERMANENT_PRO_EMAILS);
  return set.has(normalizedEmail);
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

export function resolveEntitlementState(user, env = {}) {
  const status = normalizeUserStatus(user && user.status);
  const email = normalizeEmail(user && user.email);
  const confirmedAt = String(user && user.pro_confirmed_at || "").trim();
  const hostedAccessExpiresAt = String(user && user.pro_access_expires_at || "").trim();
  const hostedAccessExpiresAtMs = Date.parse(hostedAccessExpiresAt);
  const basePlanCode = (
    status === PLAN_CODE_PLANETKA_PRO
    || status === PLAN_CODE_PLANETKA
    || status === PLAN_CODE_PLANETKA_FREE
  )
    ? status
    : PLAN_CODE_PLANETKA_FREE;
  const isStatusPaid = status === PLAN_CODE_PLANETKA_PRO;
  const hasPaidSignal = Boolean(confirmedAt || isStatusPaid || hostedAccessExpiresAt);
  const hasFutureHostedAccessExpiry = Number.isFinite(hostedAccessExpiresAtMs) && hostedAccessExpiresAtMs > Date.now();
  const hasExpiredHostedAccess = Number.isFinite(hostedAccessExpiresAtMs) && hostedAccessExpiresAtMs <= Date.now();
  const defaultResult = {
    state: "trial",
    plan_code: basePlanCode,
    commercial_use_allowed: basePlanCode === PLAN_CODE_PLANETKA_PRO,
    subscription_status: "inactive",
    is_permanent_paid: false,
    is_provisional_paid: false,
    is_expired_provisional: false,
    source: "trial",
    email,
    hosted_streaming_access_expires_at: "",
  };
  if (user && isBlockedStatus(user.status)) {
    return {
      ...defaultResult,
      state: "blocked",
      plan_code: "blocked",
      source: "blocked",
    };
  }
  if (isBetaUnrestrictedAccessEnabled(env)) {
    return {
      ...defaultResult,
      state: "permanent_paid",
      plan_code: PLAN_CODE_PLANETKA_PRO,
      commercial_use_allowed: true,
      subscription_status: "active",
      is_permanent_paid: true,
      source: "beta_unrestricted",
      hosted_streaming_access_expires_at: "",
    };
  }
  if (isPermanentProEmail(email, env)) {
    return {
      ...defaultResult,
      state: "permanent_paid",
      plan_code: PLAN_CODE_PLANETKA_PRO,
      commercial_use_allowed: true,
      subscription_status: "active",
      is_permanent_paid: true,
      source: "allowlist",
      hosted_streaming_access_expires_at: "",
    };
  }
  if (hasPaidSignal && hasExpiredHostedAccess) {
    return {
      ...defaultResult,
      state: "expired_paid",
      source: "expired",
      hosted_streaming_access_expires_at: hostedAccessExpiresAt,
    };
  }
  if (hasFutureHostedAccessExpiry) {
    return {
      ...defaultResult,
      state: "permanent_paid",
      plan_code: PLAN_CODE_PLANETKA_PRO,
      commercial_use_allowed: true,
      subscription_status: "active",
      is_permanent_paid: true,
      source: confirmedAt ? "confirmed" : "expiry",
      hosted_streaming_access_expires_at: hostedAccessExpiresAt,
    };
  }
  if (hasPaidSignal) {
    return {
      ...defaultResult,
      state: "trial",
      source: "paid_signal_without_active_access",
      hosted_streaming_access_expires_at: hostedAccessExpiresAt,
    };
  }
  return defaultResult;
}

export function subscriptionStatusForUser(user, env = {}) {
  void env;
  if (user && isBlockedStatus(user.status)) {
    return "inactive";
  }
  return "active";
}

export function normalizeRequestedPlan(value) {
  const normalized = normalizePlanCode(value);
  if (normalized === PLAN_CODE_PLANETKA_PRO) {
    return PLAN_CODE_PLANETKA_PRO;
  }
  if (normalized === PLAN_CODE_PLANETKA) {
    return PLAN_CODE_PLANETKA;
  }
  if (normalized === PLAN_CODE_PLANETKA_STUDIO) {
    return PLAN_CODE_PLANETKA_PRO;
  }
  if (normalized === PLAN_CODE_PLANETKA_FREE) {
    return PLAN_CODE_PLANETKA_FREE;
  }
  return PLAN_CODE_PLANETKA_FREE;
}

export function resolvePolicyPlanCode(user, subscription, env = {}) {
  void subscription;
  if (user && isBlockedStatus(user.status)) {
    return "blocked";
  }
  if (isBetaUnrestrictedAccessEnabled(env)) {
    return PLAN_CODE_PLANETKA_PRO;
  }
  const entitlement = resolveEntitlementState(user, env);
  const entitlementPlan = normalizeRequestedPlan(entitlement && entitlement.plan_code);
  if (entitlementPlan === PLAN_CODE_PLANETKA_PRO) {
    return entitlementPlan;
  }
  if (
    entitlementPlan === PLAN_CODE_PLANETKA
    || entitlementPlan === PLAN_CODE_PLANETKA_FREE
  ) {
    return entitlementPlan;
  }
  const currentStatus = normalizeUserStatus(user && user.status);
  if (currentStatus === PLAN_CODE_PLANETKA_PRO) {
    return currentStatus;
  }
  if (
    currentStatus === PLAN_CODE_PLANETKA
    || currentStatus === PLAN_CODE_PLANETKA_FREE
  ) {
    return currentStatus;
  }
  return PLAN_CODE_PLANETKA_FREE;
}

export function normalizeQualityMode(value) {
  const safe = String(value || "").trim().toLowerCase();
  if (safe === "full") return "full";
  if (safe === "balanced") return "balanced";
  return "preview";
}

export function isQualityModeAllowedForPlan(planCode, qualityMode) {
  const safePlanCode = normalizeRequestedPlan(planCode);
  const safeMode = normalizeQualityMode(qualityMode);
  if (safeMode === "preview") {
    return true;
  }
  if (safeMode === "balanced") {
    return safePlanCode === PLAN_CODE_PLANETKA || safePlanCode === PLAN_CODE_PLANETKA_PRO;
  }
  if (safeMode === "full") {
    return safePlanCode === PLAN_CODE_PLANETKA_PRO;
  }
  return false;
}

export function qualityModeNotAllowedMessage(planCode, qualityMode) {
  const safePlanCode = normalizeRequestedPlan(planCode);
  const safeMode = normalizeQualityMode(qualityMode);
  if (safePlanCode === PLAN_CODE_PLANETKA_FREE) {
    return "Free tier supports Preview only. Upgrade Licence for Balanced or Full Quality.";
  }
  if (safePlanCode === PLAN_CODE_PLANETKA && safeMode === "full") {
    return "Personal tier supports Preview and Balanced. Upgrade Licence for Full Quality.";
  }
  return "Selected texture quality is not available for this account tier.";
}

export function isPaidRequestedPlan(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  return normalized === PLAN_CODE_PLANETKA_PRO;
}

export function resolvePlanCode(user, subscription, env = {}) {
  void subscription;
  const entitlement = resolveEntitlementState(user, env);
  if (entitlement && entitlement.plan_code === "blocked") {
    return "blocked";
  }
  return normalizeRequestedPlan(
    entitlement && entitlement.plan_code
      ? entitlement.plan_code
      : (user && user.status) || PLAN_CODE_PLANETKA,
  );
}

export function commercialUseAllowed(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  return normalized === PLAN_CODE_PLANETKA_PRO;
}

export function accountTierForPlanCode(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  if (normalized === PLAN_CODE_PLANETKA_PRO) return "pro";
  if (normalized === PLAN_CODE_PLANETKA) return "lite";
  return "free";
}

export function planDisplayName(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  if (normalized === PLAN_CODE_PLANETKA_PRO) return "Planetka Commercial";
  if (normalized === PLAN_CODE_PLANETKA) return "Planetka Personal";
  return "Planetka Free";
}

export function planAccessSummary(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  if (normalized === PLAN_CODE_PLANETKA_PRO) {
    return "Commercial includes unlimited global Preview, Balanced, Full Quality, and animation rendering.";
  }
  if (normalized === PLAN_CODE_PLANETKA) {
    return "Personal includes Preview and Balanced texture quality.";
  }
  return "Free includes Preview texture quality only.";
}

export function resolvePlanPriority(planCode) {
  const normalized = normalizeRequestedPlan(planCode);
  if (normalized === PLAN_CODE_PLANETKA_PRO) {
    return 2;
  }
  if (normalized === PLAN_CODE_PLANETKA) {
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
