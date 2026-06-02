export function isAdminRoutePath(path) {
  return String(path || "").startsWith("/admin/");
}

export async function dispatchAdminRoute(request, env, path, deps) {
  const {
    handleAdminAnalyticsPage,
    handleAdminAnalyticsInstallsPage,
    handleAdminAnalyticsData,
    handleAdminAnalyticsTileMapImage,
    handleAdminLoginPage,
    handleAdminPasswordLogin,
    handleAdminSessionStartPage,
    handleAdminSessionStart,
    handleAdminSessionLogout,
    handleAdminInstallBlock,
    handleAdminInstallUnblock,
    handleAdminInstallHardBlock,
    handleAdminQaAuthReset,
  } = deps;

  switch (path) {
    case "/admin/analytics":
      if (request.method === "GET") {
        return await handleAdminAnalyticsPage(request, env);
      }
      return null;
    case "/admin/analytics/installs":
      if (request.method === "GET") {
        return await handleAdminAnalyticsInstallsPage(request, env);
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
    case "/admin/installs/block":
      if (request.method === "POST") {
        return await handleAdminInstallBlock(request, env);
      }
      return null;
    case "/admin/installs/unblock":
      if (request.method === "POST") {
        return await handleAdminInstallUnblock(request, env);
      }
      return null;
    case "/admin/installs/hard-block":
      if (request.method === "POST") {
        return await handleAdminInstallHardBlock(request, env);
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
