import type { NextRequest } from "next/server";

// Server-side proxy to the FastAPI backend. The browser only talks to this
// route; the API address and the dev-auth seller header stay on the server.
export const dynamic = "force-dynamic";

const FORWARD_REQUEST_HEADERS = ["content-type", "accept", "idempotency-key"];

async function proxy(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  const { path } = await ctx.params;
  if (
    !path.length ||
    path.some((s) => !s || s === "." || s === ".." || /[\\/]/.test(s))
  )
    return Response.json({ detail: "Not found." }, { status: 404 });
  const base = (process.env.API_BASE_URL || "http://127.0.0.1:8000").replace(
    /\/+$/,
    "",
  );
  const joined = path.map(encodeURIComponent).join("/");
  const target =
    joined === "healthz"
      ? `${base}/healthz`
      : `${base}/v1/${joined}${req.nextUrl.search}`;
  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("x-seller-id", process.env.DEMO_SELLER_ID || "demo-seller");
  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  try {
    const upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? await req.arrayBuffer() : undefined,
      cache: "no-store",
    });
    const out = new Headers();
    const type = upstream.headers.get("content-type");
    if (type) out.set("content-type", type);
    out.set("cache-control", "no-store");
    const empty = upstream.status === 204 || upstream.status === 304;
    return new Response(empty ? null : upstream.body, {
      status: upstream.status,
      headers: out,
    });
  } catch {
    return Response.json(
      { detail: "The research service is unavailable." },
      { status: 502 },
    );
  }
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
