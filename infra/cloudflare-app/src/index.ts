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

function renderEmbeddedApp(request: Request, origin: URL): Response {
  const incoming = new URL(request.url);
  const embedUrl = new URL("/", origin);
  incoming.searchParams.forEach((value, key) => {
    embedUrl.searchParams.append(key, value);
  });
  embedUrl.searchParams.set("embed", "true");

  const html = `<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <title>Viral Intel</title>
  <style>
    html,body{width:100%;height:100%;margin:0;background:#fff;overflow:hidden}
    iframe{display:block;width:100%;height:100%;border:0;background:#fff}
  </style>
</head>
<body>
  <iframe src="${embedUrl.toString()}" title="Viral Intel" allow="clipboard-read; clipboard-write; fullscreen" referrerpolicy="strict-origin-when-cross-origin"></iframe>
</body>
</html>`;

  return new Response(html, {
    status: 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "strict-origin-when-cross-origin",
      "Content-Security-Policy": `default-src 'none'; frame-src ${origin.origin}; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'`,
    },
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
          hosting: "streamlit-community-cloud-embed",
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

    const origin = getStreamlitOrigin(env);

    if (url.pathname === "/viral-intel/_shell-health") {
      return responseJson({
        ok: true,
        service: "viral-intel-shell",
        hosting: "streamlit-community-cloud-embed",
        origin_host: origin.host,
      });
    }

    if (url.pathname !== "/viral-intel/") {
      return responseJson({ ok: false, error: "Not found" }, 404);
    }

    return renderEmbeddedApp(request, origin);
  },
} satisfies ExportedHandler<RuntimeEnv>;
