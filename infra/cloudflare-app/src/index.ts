import { Container } from "@cloudflare/containers";
import { env as runtimeBindings } from "cloudflare:workers";

type RuntimeEnv = CloudflareEnv & {
  VIRAL_INTEL: DurableObjectNamespace<ViralIntelContainer>;
  VIRAL_INTEL_BASIC_USER?: string;
  VIRAL_INTEL_BASIC_PASSWORD?: string;
  CLOUDFLARE_MEMORY_URL?: string;
  CLOUDFLARE_MEMORY_SECRET?: string;
  GOOGLE_API_KEY?: string;
  OPENAI_API_KEY?: string;
  ANTHROPIC_API_KEY?: string;
  APIFY_API_TOKEN?: string;
  INSTAGRAM_ACCESS_TOKEN?: string;
  INSTAGRAM_USER_ID?: string;
};

const bindings = runtimeBindings as unknown as RuntimeEnv;
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
    const user = decoded.slice(0, separator);
    const password = decoded.slice(separator + 1);
    return constantTimeEqual(user, expectedUser) && constantTimeEqual(password, expectedPassword);
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

export class ViralIntelContainer extends Container {
  defaultPort = 8080;
  sleepAfter = "20m";

  envVars = {
    VIRAL_INTEL_EXECUTION: "cloudflare",
    DATA_DIR: "/tmp/viral-intel-data",
    LOCAL_MEDIA_DIR: "/tmp/viral-intel-data/inbox",
    ENABLE_TRANSCRIPTION: "false",
    EPHEMERAL_MODE: "true",
    ENABLE_PERSISTENCE: "true",
    ENABLE_NATIVE_VIDEO_AI: "true",
    ENABLE_SEMANTIC_COMMENTS: "true",
    MAX_UPLOAD_MB: "100",
    COMMAND_TIMEOUT_SECONDS: "120",
    AI_PROVIDER: "auto",
    CLOUDFLARE_MEMORY_URL: bindings.CLOUDFLARE_MEMORY_URL ?? "",
    CLOUDFLARE_MEMORY_SECRET: bindings.CLOUDFLARE_MEMORY_SECRET ?? "",
    GOOGLE_API_KEY: bindings.GOOGLE_API_KEY ?? "",
    OPENAI_API_KEY: bindings.OPENAI_API_KEY ?? "",
    ANTHROPIC_API_KEY: bindings.ANTHROPIC_API_KEY ?? "",
    APIFY_API_TOKEN: bindings.APIFY_API_TOKEN ?? "",
    INSTAGRAM_ACCESS_TOKEN: bindings.INSTAGRAM_ACCESS_TOKEN ?? "",
    INSTAGRAM_USER_ID: bindings.INSTAGRAM_USER_ID ?? "",
  };

  override onStart(): void {
    console.log(JSON.stringify({ event: "viral_intel_container_started" }));
  }

  override onStop(): void {
    console.log(JSON.stringify({ event: "viral_intel_container_stopped" }));
  }

  override onError(error: unknown): void {
    const message = error instanceof Error ? error.message : String(error);
    console.error(JSON.stringify({ event: "viral_intel_container_error", message }));
  }
}

export default {
  async fetch(request: Request, env: RuntimeEnv): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/viral-intel/_edge-health") {
      return responseJson({
        ok: true,
        service: "viral-intel-edge",
        container: "cloudflare",
        memory_configured: Boolean(env.CLOUDFLARE_MEMORY_URL && env.CLOUDFLARE_MEMORY_SECRET),
        ai_configured: Boolean(env.GOOGLE_API_KEY || env.OPENAI_API_KEY || env.ANTHROPIC_API_KEY),
      });
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

    const container = env.VIRAL_INTEL.getByName("primary");
    return container.fetch(request);
  },
} satisfies ExportedHandler<RuntimeEnv>;
