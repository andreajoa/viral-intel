type RuntimeEnv = CloudflareEnv & {
  VIRAL_INTEL_BASIC_USER?: string;
  VIRAL_INTEL_BASIC_PASSWORD?: string;
  STREAMLIT_ORIGIN?: string;
};

const encoder = new TextEncoder();

function responseJson(data: Record<string, unknown>, status = 200): Response {
  return Response.json(data, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    },
  });
}

function constantTimeEqual(left: string, right: string): boolean {
  const a = encoder.encode(left);
  const b = encoder.encode(right);
  const length = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let index = 0; index < length; index += 1) {
    diff |= (a[index] ?? 0) ^ (b[index] ?? 0);
  }
  return diff === 0;
}

function validBasicAuth(request: Request, env: RuntimeEnv): boolean {
  const expectedUser = (env.VIRAL_INTEL_BASIC_USER ?? "andre").trim();
  const expectedPassword = (env.VIRAL_INTEL_BASIC_PASSWORD ?? "").trim();
  if (!expectedPassword) return false;

  const header = request.headers.get("Authorization") ?? "";
  if (!header.startsWith("Basic ")) return false;

  try {
    const decoded = atob(header.slice(6));
    const separator = decoded.indexOf(":");
    if (separator < 0) return false;
    return (
      constantTimeEqual(decoded.slice(0, separator), expectedUser) &&
      constantTimeEqual(decoded.slice(separator + 1), expectedPassword)
    );
  } catch {
    return false;
  }
}

function authRequired(): Response {
  return new Response("Authentication required", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="Viral Intel", charset="UTF-8"',
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function getStreamlitOrigin(env: RuntimeEnv): URL {
  const configured = (env.STREAMLIT_ORIGIN ?? "").trim();
  if (!configured) throw new Error("STREAMLIT_ORIGIN is not configured");
  const url = new URL(configured);
  if (url.protocol !== "https:") throw new Error("STREAMLIT_ORIGIN must use HTTPS");
  return url;
}

async function proxyToStreamlit(request: Request, env: RuntimeEnv): Promise<Response> {
  const incoming = new URL(request.url);
  const origin = getStreamlitOrigin(env);
  const target = new URL(incoming.pathname + incoming.search, origin);

  const headers = new Headers(request.headers);
  headers.delete("Authorization");
  headers.delete("Host");
  headers.set("X-Forwarded-Host", incoming.host);
  headers.set("X-Forwarded-Proto", "https");

  const init: RequestInit = {
    method: request.method,
    headers,
    redirect: "manual",
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = request.body;
  }

  const upstream = await fetch(new Request(target.toString(), init));
  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.set("X-Viral-Intel-Proxy", "cloudflare-free");

  const location = responseHeaders.get("Location");
  if (location) {
    try {
      const redirect = new URL(location, origin);
      if (redirect.origin === origin.origin) {
        redirect.protocol = incoming.protocol;
        redirect.host = incoming.host;
        responseHeaders.set("Location", redirect.toString());
      }
    } catch {
      // Keep non-URL Location values unchanged.
    }
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
    webSocket: upstream.webSocket,
  });
}

export default {
  async fetch(request: Request, env: RuntimeEnv): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/viral-intel/_edge-health") {
      try {
        const origin = getStreamlitOrigin(env);
        return responseJson({
          ok: true,
          service: "viral-intel-edge",
          hosting: "streamlit-community-cloud",
          cloudflare_plan: "free-compatible",
          origin_host: origin.host,
        });
      } catch (error) {
        return responseJson(
          {
            ok: false,
            service: "viral-intel-edge",
            error: error instanceof Error ? error.message : String(error),
          },
          503,
        );
      }
    }

    if (url.pathname === "/viral-intel") {
      url.pathname = "/viral-intel/";
      return Response.redirect(url.toString(), 308);
    }

    if (!url.pathname.startsWith("/viral-intel/")) {
      return responseJson({ ok: false, error: "Not found" }, 404);
    }

    if (!validBasicAuth(request, env)) {
      return authRequired();
    }

    try {
      return await proxyToStreamlit(request, env);
    } catch (error) {
      console.error(
        JSON.stringify({
          event: "streamlit_proxy_error",
          message: error instanceof Error ? error.message : String(error),
        }),
      );
      return responseJson({ ok: false, error: "Upstream unavailable" }, 502);
    }
  },
} satisfies ExportedHandler<RuntimeEnv>;
