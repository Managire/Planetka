export const PLAN_CODE_FREE = "free";
export const PLAN_CODE_PERSONAL = "personal";
export const PLAN_CODE_PROFESSIONAL = "professional";

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
    return PLAN_CODE_PERSONAL;
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
  return normalized === PLAN_CODE_PROFESSIONAL ? PLAN_CODE_PROFESSIONAL : PLAN_CODE_PERSONAL;
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
  return "Selected texture quality is available.";
}

export function isProfessionalPlan(planCode) {
  return normalizeRequestedPlan(planCode) === PLAN_CODE_PROFESSIONAL;
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
  return "Personal accounts can stream Planetka free locations: New Zealand and Iceland. Upgrade to Professional for global access.";
}

export function accountTierForPlanCode(planCode) {
  return normalizeRequestedPlan(planCode);
}

export function planDisplayName(planCode) {
  return normalizeRequestedPlan(planCode) === PLAN_CODE_PROFESSIONAL ? "Professional" : "Personal";
}

export function planAccessSummary(planCode) {
  return normalizeRequestedPlan(planCode) === PLAN_CODE_PROFESSIONAL
    ? "Professional account: Preview, Balanced, and Full Quality streaming."
    : "Personal account: Preview, Balanced, and Full Quality streaming.";
}

export function resolvePlanPriority(planCode) {
  return normalizeRequestedPlan(planCode) === PLAN_CODE_PROFESSIONAL ? 10 : 0;
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
