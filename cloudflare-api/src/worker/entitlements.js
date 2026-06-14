export const ACCESS_STATUS_ACTIVE = "active";
export const ACCESS_STATUS_BLOCKED = "blocked";
export const ACCESS_TIER_FREE = "free";
export const ACCESS_TIER_PRO = "pro";
export const ACCESS_TIER_STUDIO = "studio";

const DEFAULT_DEVICE_LIMIT_EXEMPT_EMAILS = "tom.griger@gmail.com";

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

export function parseCsvEmailSet(value, fallback = "") {
  const set = new Set();
  const source = String(value || fallback || "").trim();
  if (!source) return set;
  for (const token of source.split(",")) {
    const email = normalizeEmail(token);
    if (email && email.includes("@")) set.add(email);
  }
  return set;
}

export function isDeviceLimitExemptEmail(email, env = {}) {
  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail) return false;
  const set = parseCsvEmailSet(env.DEVICE_LIMIT_EXEMPT_EMAILS, DEFAULT_DEVICE_LIMIT_EXEMPT_EMAILS);
  return set.has(normalizedEmail);
}

export function isBlockedStatus(statusValue) {
  return String(statusValue || "").trim().toLowerCase() === ACCESS_STATUS_BLOCKED;
}

export function normalizeAccessStatus(value) {
  return isBlockedStatus(value) ? ACCESS_STATUS_BLOCKED : ACCESS_STATUS_ACTIVE;
}

export function normalizeRequestedAccessStatus(value) {
  return normalizeAccessStatus(value);
}

export function defaultSignupAccessStatus(env = {}) {
  void env;
  return ACCESS_STATUS_ACTIVE;
}

export function normalizeAccessTier(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === ACCESS_TIER_PRO) return ACCESS_TIER_PRO;
  if (normalized === ACCESS_TIER_STUDIO || normalized === "planetka_studio") return ACCESS_TIER_STUDIO;
  if (normalized === "private") return ACCESS_TIER_PRO;
  return ACCESS_TIER_FREE;
}

export function normalizeRequestedAccessTier(value) {
  return normalizeAccessTier(value);
}

export function defaultSignupAccessTier(env = {}) {
  void env;
  return ACCESS_TIER_FREE;
}

export function accessTierDisplayName(accessTier) {
  const normalized = normalizeAccessTier(accessTier);
  if (normalized === ACCESS_TIER_PRO) return "Pro";
  if (normalized === ACCESS_TIER_STUDIO) return "Studio";
  return "Free";
}

export function normalizeInstallEdition(value) {
  return normalizeAccessTier(value);
}

export function installEditionDisplayName(edition) {
  return accessTierDisplayName(edition);
}

export function resolvePolicyAccessStatus(user, env = {}) {
  void env;
  return isBlockedStatus(user && user.status) ? ACCESS_STATUS_BLOCKED : ACCESS_STATUS_ACTIVE;
}

export function resolveAccessStatus(user, env = {}) {
  return resolvePolicyAccessStatus(user, env);
}

export function normalizeQualityMode(value) {
  const safe = String(value || "").trim().toLowerCase();
  if (safe === "full") return "full";
  if (safe === "balanced") return "balanced";
  return "preview";
}

export function isQualityModeAllowedForAccess(accessStatus, qualityMode) {
  void accessStatus;
  void qualityMode;
  return true;
}

export function qualityModeNotAllowedMessage(accessStatus, qualityMode) {
  void accessStatus;
  void qualityMode;
  return "Selected texture quality is not available.";
}

export function isTileFileAllowedForEdition(installEdition, fileName) {
  void installEdition;
  void fileName;
  return true;
}

export function normalizeTileSessionFeature(value) {
  const safe = String(value || "").trim().toLowerCase();
  if (safe === "final_animation_render") return "final_animation_render";
  if (safe === "panorama") return "panorama";
  return "";
}

export function isTileSessionFeatureAllowedForEdition(installEdition, feature) {
  const safeFeature = normalizeTileSessionFeature(feature);
  if (safeFeature !== "final_animation_render") return true;
  return normalizeAccessTier(installEdition) === ACCESS_TIER_STUDIO;
}

export function isTileFileAllowedForAccess(accessStatus, fileName) {
  void accessStatus;
  return isTileFileAllowedForEdition(ACCESS_TIER_PRO, fileName);
}

export function tileFileNotAllowedMessage(accessStatus, fileName) {
  void accessStatus;
  void fileName;
  return "This texture file is not available.";
}

export function accessStatusDisplayName(accessStatus) {
  return normalizeRequestedAccessStatus(accessStatus) === ACCESS_STATUS_BLOCKED ? "Blocked" : "Active";
}

export function accessStatusSummary(accessStatus) {
  return normalizeRequestedAccessStatus(accessStatus) === ACCESS_STATUS_BLOCKED
    ? "Blocked access."
    : "Active Planetka Cloud access.";
}

export function resolveAccessStatusPriority(accessStatus) {
  return normalizeRequestedAccessStatus(accessStatus) === ACCESS_STATUS_BLOCKED ? -1 : 20;
}
