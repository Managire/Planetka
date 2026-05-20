export const PLAN_CODE_FREE = "free";
export const PLAN_CODE_PERSONAL = PLAN_CODE_FREE;
export const PLAN_CODE_INDIE = "indie";
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
  if (["indie", "balanced"].includes(normalized)) {
    return PLAN_CODE_INDIE;
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
  if (normalized === PLAN_CODE_INDIE) return PLAN_CODE_INDIE;
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
  if (plan === PLAN_CODE_INDIE) return quality === "preview" || quality === "balanced";
  return quality === "preview";
}

export function qualityModeNotAllowedMessage(planCode, qualityMode) {
  const plan = normalizeRequestedPlan(planCode);
  const quality = normalizeQualityMode(qualityMode);
  if (plan === PLAN_CODE_INDIE && quality === "full") {
    return "Full texture quality requires a Pro account.";
  }
  if (plan === PLAN_CODE_FREE && quality !== "preview") {
    return "Balanced and Full texture quality require an Indie or Pro account.";
  }
  return "Selected texture quality is not available for this account.";
}

export function isProfessionalPlan(planCode) {
  return normalizeRequestedPlan(planCode) === PLAN_CODE_PROFESSIONAL;
}

export function isIndiePlan(planCode) {
  return normalizeRequestedPlan(planCode) === PLAN_CODE_INDIE;
}

const PERSONAL_FREE_REGION_BOXES = [
  {
    id: "new_zealand",
    label: "New Zealand",
    boxes: [
      { latMin: -55, latMax: -29, lonMin: 156, lonMax: 180 },
      { latMin: -55, latMax: -29, lonMin: -180, lonMax: -168 },
    ],
  },
  {
    id: "iceland",
    label: "Iceland",
    boxes: [
      { latMin: 62, latMax: 68, lonMin: -26, lonMax: -11 },
    ],
  },
];

function normalizeLongitude(lon) {
  const numeric = Number(lon);
  if (!Number.isFinite(numeric)) return NaN;
  let normalized = numeric;
  while (normalized < -180) normalized += 360;
  while (normalized > 180) normalized -= 360;
  return normalized;
}

function pointInBox(lat, lon, box) {
  return lat >= box.latMin && lat <= box.latMax && lon >= box.lonMin && lon <= box.lonMax;
}

function boxesIntersect(a, b) {
  return a.latMin < b.latMax
    && a.latMax > b.latMin
    && a.lonMin < b.lonMax
    && a.lonMax > b.lonMin;
}

export function personalFreeRegionForPoint(latValue, lonValue) {
  const lat = Number(latValue);
  const lon = normalizeLongitude(lonValue);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  for (const region of PERSONAL_FREE_REGION_BOXES) {
    if (region.boxes.some((box) => pointInBox(lat, lon, box))) {
      return { id: region.id, label: region.label };
    }
  }
  return null;
}

function parsePlanetkaTileFileName(fileName) {
  const match = /^(?:S2|EL|WT|PO)_x(\d+)_y(\d+)_z(\d+)_d(\d+)\.(?:exr|tif)$/i.exec(String(fileName || "").trim());
  if (!match) return null;
  const x = Number.parseInt(match[1], 10);
  const y = Number.parseInt(match[2], 10);
  const d = Number.parseInt(match[4], 10);
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(d) || d <= 0) {
    return null;
  }
  const lonMin = Math.max(-180, x * d - 180);
  const lonMax = Math.min(180, lonMin + d);
  const latMax = Math.min(90, 90 - y * d);
  const latMin = Math.max(-90, latMax - d);
  return { latMin, latMax, lonMin, lonMax };
}

export function personalFreeRegionForTileFileName(fileName, expectedRegionId = "") {
  const tileBox = parsePlanetkaTileFileName(fileName);
  if (!tileBox) return null;
  const expected = String(expectedRegionId || "").trim();
  for (const region of PERSONAL_FREE_REGION_BOXES) {
    if (expected && region.id !== expected) continue;
    if (region.boxes.some((box) => boxesIntersect(tileBox, box))) {
      return { id: region.id, label: region.label };
    }
  }
  return null;
}

export function personalFreeLocationBlockedMessage() {
  return "Free accounts can stream Preview texture quality worldwide. Upgrade to Indie for Balanced or Pro for Full.";
}

export function accountTierForPlanCode(planCode) {
  return normalizeRequestedPlan(planCode);
}

export function planDisplayName(planCode) {
  const plan = normalizeRequestedPlan(planCode);
  if (plan === PLAN_CODE_PROFESSIONAL) return "Pro";
  if (plan === PLAN_CODE_INDIE) return "Indie";
  return "Free";
}

export function planAccessSummary(planCode) {
  const plan = normalizeRequestedPlan(planCode);
  if (plan === PLAN_CODE_PROFESSIONAL) {
    return "Pro account: Preview, Balanced, and Full texture quality streaming.";
  }
  if (plan === PLAN_CODE_INDIE) {
    return "Indie account: Preview and Balanced texture quality streaming.";
  }
  return "Free account: Preview texture quality streaming.";
}

export function resolvePlanPriority(planCode) {
  const plan = normalizeRequestedPlan(planCode);
  if (plan === PLAN_CODE_PROFESSIONAL) return 20;
  if (plan === PLAN_CODE_INDIE) return 10;
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
