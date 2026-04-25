const DEFAULT_BETA_ACCESS_MODE = "restricted";

export function parseBooleanFlag(value) {
  if (typeof value === "boolean") {
    return value;
  }
  const normalized = String(value || "").trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

export function parsePositiveNumber(value, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return parsed;
}

export function parseNonNegativeInteger(value, fallback = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(0, Math.floor(parsed));
}

export function isLegacyBetaForceProTierEnabled(env = {}) {
  const raw = env.BETA_FORCE_PRO_TIER;
  if (raw === undefined || raw === null || String(raw).trim() === "") {
    return false;
  }
  return parseBooleanFlag(raw);
}

export function normalizeBetaAccessMode(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) {
    return "";
  }
  if (normalized === "unrestricted") {
    return "unrestricted";
  }
  if (
    normalized === "restricted"
    || normalized === "off"
    || normalized === "disabled"
    || normalized === "normal"
  ) {
    return "restricted";
  }
  return "";
}

export function resolveBetaAccessMode(env = {}) {
  const explicitMode = normalizeBetaAccessMode(env.BETA_ACCESS_MODE);
  if (explicitMode) {
    return explicitMode;
  }
  if (isLegacyBetaForceProTierEnabled(env)) {
    return "unrestricted";
  }
  return DEFAULT_BETA_ACCESS_MODE;
}

export function isBetaUnrestrictedAccessEnabled(env = {}) {
  return resolveBetaAccessMode(env) === "unrestricted";
}
