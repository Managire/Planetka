export function isAdminRoutePath(path) {
  return String(path || "").startsWith("/admin/");
}

export async function dispatchAdminRoute(request, env, path, deps) {
  const {
    handleAdminAnalyticsPage,
    handleAdminAnalyticsUsersPage,
    handleAdminAnalyticsData,
    handleAdminAnalyticsTileMapImage,
    handleAdminLoginPage,
    handleAdminPasswordLogin,
    handleAdminSessionStartPage,
    handleAdminSessionStart,
    handleAdminSessionLogout,
    handleAdminUserBlock,
    handleAdminUserUnblock,
    handleAdminUserHardBlock,
    handleAdminUserSetPlan,
    handleAdminQaAuthReset,
  } = deps;

  switch (path) {
    case "/admin/analytics":
      if (request.method === "GET") {
        return await handleAdminAnalyticsPage(request, env);
      }
      return null;
    case "/admin/analytics/users":
      if (request.method === "GET") {
        return await handleAdminAnalyticsUsersPage(request, env);
      }
      return null;
    case "/admin/analytics/data":
      if (request.method === "GET") {
        return await handleAdminAnalyticsData(request, env);
      }
      return null;
    case "/admin/analytics/world-map.jpg":
      if (request.method === "GET") {
        return await handleAdminAnalyticsTileMapImage(request, env);
      }
      return null;
    case "/admin/login":
      if (request.method === "GET") {
        return await handleAdminLoginPage(request, env);
      }
      if (request.method === "POST") {
        return await handleAdminPasswordLogin(request, env);
      }
      return null;
    case "/admin/session/start":
      if (request.method === "GET") {
        return await handleAdminSessionStartPage(request, env);
      }
      if (request.method === "POST") {
        return await handleAdminSessionStart(request, env);
      }
      return null;
    case "/admin/session/logout":
      if (request.method === "GET") {
        return await handleAdminSessionLogout(request, env);
      }
      return null;
    case "/admin/users/block":
      if (request.method === "POST") {
        return await handleAdminUserBlock(request, env);
      }
      return null;
    case "/admin/users/unblock":
      if (request.method === "POST") {
        return await handleAdminUserUnblock(request, env);
      }
      return null;
    case "/admin/users/hard-block":
      if (request.method === "POST") {
        return await handleAdminUserHardBlock(request, env);
      }
      return null;
    case "/admin/users/set-plan":
      if (request.method === "POST") {
        return await handleAdminUserSetPlan(request, env);
      }
      return null;
    case "/admin/qa/auth-reset":
      if (request.method === "POST") {
        return await handleAdminQaAuthReset(request, env);
      }
      return null;
    default:
      return null;
  }
}
