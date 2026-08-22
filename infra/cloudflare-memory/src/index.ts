const encoder = new TextEncoder();
type Env = CloudflareEnv & { API_SECRET: string };

interface ComparableRow {
  report_id: string;
  post_key: string;
  captured_at: string;
  metrics_json: string;
  benchmark_json: string;
  fingerprint_json: string;
}

interface TimelineRow {
  report_id: string;
  captured_at: string;
  metrics_json: string;
  benchmark_json: string;
}

type JsonRecord = Record<string, unknown>;

function json(data: JsonRecord, status = 200): Response {
  return Response.json(data, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, name: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`Campo obrigatório ausente: ${name}`);
  }
  return value.trim();
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function decodeHex(value: string): Uint8Array | null {
  if (!/^[0-9a-f]{64}$/i.test(value)) return null;
  const output = new Uint8Array(value.length / 2);
  for (let index = 0; index < value.length; index += 2) {
    output[index / 2] = Number.parseInt(value.slice(index, index + 2), 16);
  }
  return output;
}

async function authorized(request: Request, env: Env, body: string): Promise<boolean> {
  const timestamp = request.headers.get("X-VI-Timestamp") ?? "";
  const signature = request.headers.get("X-VI-Signature") ?? "";
  const unix = Number(timestamp);
  if (!Number.isFinite(unix) || Math.abs(Date.now() / 1000 - unix) > 300) return false;

  const signatureBytes = decodeHex(signature);
  if (!signatureBytes || !env.API_SECRET) return false;

  const url = new URL(request.url);
  const canonical = `${timestamp}\n${request.method.toUpperCase()}\n${url.pathname}${url.search}\n${body}`;
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(env.API_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  return crypto.subtle.verify("HMAC", key, signatureBytes, encoder.encode(canonical));
}

function parsedJson(value: string): unknown {
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

async function saveReport(env: Env, body: JsonRecord): Promise<Response> {
  const reportId = requiredString(body.report_id, "report_id");
  const profileKey = requiredString(body.profile_key, "profile_key");
  const postKey = requiredString(body.post_key, "post_key");
  const platform = requiredString(body.platform, "platform");
  const format = requiredString(body.format, "format");
  const capturedAt = requiredString(body.captured_at, "captured_at");
  const generatedAt = requiredString(body.generated_at, "generated_at");

  await env.DB.prepare(
    `INSERT OR REPLACE INTO reports(
      report_id, profile_key, post_key, platform, format, captured_at,
      generated_at, metrics_json, benchmark_json, fingerprint_json, envelope_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(
      reportId,
      profileKey,
      postKey,
      platform,
      format,
      capturedAt,
      generatedAt,
      JSON.stringify(body.metrics ?? {}),
      JSON.stringify(body.benchmark ?? {}),
      JSON.stringify(body.fingerprint ?? {}),
      JSON.stringify(body.envelope ?? {}),
    )
    .run();

  return json({ ok: true, report_id: reportId });
}

async function comparableReports(env: Env, url: URL): Promise<Response> {
  const profileKey = requiredString(url.searchParams.get("profile_key"), "profile_key");
  const platform = requiredString(url.searchParams.get("platform"), "platform");
  const format = requiredString(url.searchParams.get("format"), "format");
  const exclude = url.searchParams.get("exclude_report_id")?.trim() ?? "";
  const requestedLimit = Number(url.searchParams.get("limit") ?? "250");
  const limit = Math.max(1, Math.min(Number.isFinite(requestedLimit) ? requestedLimit : 250, 1000));

  const statement = exclude
    ? env.DB.prepare(
        `SELECT report_id, post_key, captured_at, metrics_json, benchmark_json, fingerprint_json
         FROM reports
         WHERE profile_key=? AND platform=? AND format=? AND report_id<>?
         ORDER BY captured_at DESC LIMIT ?`,
      ).bind(profileKey, platform, format, exclude, limit)
    : env.DB.prepare(
        `SELECT report_id, post_key, captured_at, metrics_json, benchmark_json, fingerprint_json
         FROM reports
         WHERE profile_key=? AND platform=? AND format=?
         ORDER BY captured_at DESC LIMIT ?`,
      ).bind(profileKey, platform, format, limit);

  const result = await statement.all<ComparableRow>();
  const reports = (result.results ?? []).map((row) => ({
    report_id: row.report_id,
    post_id: row.post_key,
    captured_at: row.captured_at,
    metrics: parsedJson(row.metrics_json),
    benchmark: parsedJson(row.benchmark_json),
    fingerprint: parsedJson(row.fingerprint_json),
  }));
  return json({ ok: true, reports });
}

async function postTimeline(env: Env, url: URL): Promise<Response> {
  const profileKey = requiredString(url.searchParams.get("profile_key"), "profile_key");
  const postKey = requiredString(url.searchParams.get("post_key"), "post_key");
  const result = await env.DB.prepare(
    `SELECT report_id, captured_at, metrics_json, benchmark_json
     FROM reports WHERE profile_key=? AND post_key=? ORDER BY captured_at ASC`,
  )
    .bind(profileKey, postKey)
    .all<TimelineRow>();

  const timeline = (result.results ?? []).map((row) => ({
    report_id: row.report_id,
    captured_at: row.captured_at,
    metrics: parsedJson(row.metrics_json),
    benchmark: parsedJson(row.benchmark_json),
  }));
  return json({ ok: true, timeline });
}

async function createExperiment(env: Env, body: JsonRecord): Promise<Response> {
  const experimentId = requiredString(body.experiment_id, "experiment_id");
  const profileKey = requiredString(body.profile_key, "profile_key");
  const createdAt = requiredString(body.created_at, "created_at");
  const hypothesis = requiredString(body.hypothesis, "hypothesis");
  const changeOneThing = requiredString(body.change_one_thing, "change_one_thing");
  const primaryMetric = requiredString(body.primary_metric, "primary_metric");

  await env.DB.prepare(
    `INSERT INTO experiments(
      experiment_id, profile_key, created_at, status, hypothesis,
      change_one_thing, primary_metric, source_report_id, result_json
    ) VALUES (?, ?, ?, 'PLANNED', ?, ?, ?, ?, '{}')`,
  )
    .bind(
      experimentId,
      profileKey,
      createdAt,
      hypothesis,
      changeOneThing,
      primaryMetric,
      optionalString(body.source_report_id),
    )
    .run();
  return json({ ok: true, experiment_id: experimentId }, 201);
}

async function completeExperiment(env: Env, experimentId: string, body: JsonRecord): Promise<Response> {
  const result = await env.DB.prepare(
    "UPDATE experiments SET status='COMPLETED', result_json=? WHERE experiment_id=?",
  )
    .bind(JSON.stringify(body.result ?? {}), experimentId)
    .run();
  if (!result.meta.changes) return json({ ok: false, error: "Experimento não encontrado" }, 404);
  return json({ ok: true, experiment_id: experimentId });
}

async function route(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/health") {
    const row = await env.DB.prepare("SELECT value FROM metadata WHERE key='schema_version'").first<{
      value: string;
    }>();
    return json({
      ok: true,
      service: "viral-intel-memory",
      schema_version: row?.value ?? "unknown",
    });
  }

  if (!url.pathname.startsWith("/v1/")) return json({ ok: false, error: "Not found" }, 404);
  const bodyText = request.method === "GET" || request.method === "HEAD" ? "" : await request.text();
  if (!(await authorized(request, env, bodyText))) {
    return json({ ok: false, error: "Unauthorized" }, 401);
  }

  let body: JsonRecord = {};
  if (bodyText) {
    const candidate = parsedJson(bodyText);
    if (!isRecord(candidate)) return json({ ok: false, error: "JSON inválido" }, 400);
    body = candidate;
  }

  if (request.method === "POST" && url.pathname === "/v1/reports") return saveReport(env, body);
  if (request.method === "GET" && url.pathname === "/v1/reports/comparable") {
    return comparableReports(env, url);
  }
  if (request.method === "GET" && url.pathname === "/v1/posts/timeline") {
    return postTimeline(env, url);
  }
  if (request.method === "POST" && url.pathname === "/v1/experiments") {
    return createExperiment(env, body);
  }

  const match = url.pathname.match(/^\/v1\/experiments\/([^/]+)\/complete$/);
  if (request.method === "POST" && match?.[1]) {
    return completeExperiment(env, match[1], body);
  }
  return json({ ok: false, error: "Not found" }, 404);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      return await route(request, env);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Falha interna";
      console.error(
        JSON.stringify({ event: "request_error", path: new URL(request.url).pathname, message }),
      );
      return json(
        { ok: false, error: message.slice(0, 240) },
        message.startsWith("Campo obrigatório") ? 400 : 500,
      );
    }
  },
} satisfies ExportedHandler<Env>;
