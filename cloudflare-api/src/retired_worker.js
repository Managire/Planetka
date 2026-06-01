import { corsHeaders, json } from "./worker/responses.js";

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(env) });
    }
    return json(
      {
        ok: false,
        error: "endpoint_retired",
        message: "This Planetka endpoint has been retired.",
      },
      410,
      env,
    );
  },
};
