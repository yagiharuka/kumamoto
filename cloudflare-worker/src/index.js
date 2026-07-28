const REPOSITORY = "yagiharuka/kumamoto";
const WORKFLOW_FILE = "update.yml";
const ALLOWED_ORIGIN = "https://yagiharuka.github.io";
const BUTTON_COOLDOWN_SECONDS = 120;

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function jsonResponse(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...headers,
    },
  });
}

async function dispatchWorkflow(env, { sendEmail, trigger }) {
  if (!env.GITHUB_TOKEN) {
    throw new Error("GITHUB_TOKEN is not configured");
  }

  const response = await fetch(
    `https://api.github.com/repos/${REPOSITORY}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        "Content-Type": "application/json",
        "User-Agent": "kumamoto-news-trigger",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: {
          send_email: sendEmail,
          trigger,
        },
      }),
    },
  );

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`GitHub dispatch failed (${response.status}): ${detail}`);
  }
}

async function getCooldown(request) {
  const cache = caches.default;
  const key = new Request(new URL("/__button-cooldown", request.url), {
    method: "GET",
  });
  return { cache, key, response: await cache.match(key) };
}

async function handleButtonRequest(request, env) {
  const origin = request.headers.get("Origin");
  if (origin !== ALLOWED_ORIGIN) {
    return jsonResponse({ error: "Origin not allowed" }, 403);
  }

  const headers = corsHeaders(origin);
  const cooldown = await getCooldown(request);
  if (cooldown.response) {
    return jsonResponse(
      {
        accepted: false,
        error: "A refresh was requested recently",
        retry_after: BUTTON_COOLDOWN_SECONDS,
      },
      429,
      { ...headers, "Retry-After": String(BUTTON_COOLDOWN_SECONDS) },
    );
  }

  await dispatchWorkflow(env, { sendEmail: false, trigger: "website" });

  await cooldown.cache.put(
    cooldown.key,
    new Response("1", {
      headers: {
        "Cache-Control": `public, max-age=${BUTTON_COOLDOWN_SECONDS}`,
      },
    }),
  );

  return jsonResponse({ accepted: true }, 202, headers);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin");

    if (request.method === "OPTIONS") {
      if (origin !== ALLOWED_ORIGIN) {
        return new Response(null, { status: 403 });
      }
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    if (request.method === "GET" && url.pathname === "/health") {
      return jsonResponse({ ok: true, service: "kumamoto-news-trigger" });
    }

    if (request.method === "POST" && url.pathname === "/api/refresh") {
      try {
        return await handleButtonRequest(request, env);
      } catch (error) {
        console.error(error);
        return jsonResponse(
          { accepted: false, error: "Unable to start refresh" },
          502,
          origin === ALLOWED_ORIGIN ? corsHeaders(origin) : {},
        );
      }
    }

    return jsonResponse({ error: "Not found" }, 404);
  },

  async scheduled(controller, env, ctx) {
    const minute = new Date(controller.scheduledTime).getUTCMinutes();
    const sendEmail = minute === 0;
    ctx.waitUntil(
      dispatchWorkflow(env, {
        sendEmail,
        trigger: "cloudflare-cron",
      }),
    );
  },
};
