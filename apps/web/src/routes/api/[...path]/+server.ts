import { env } from '$env/dynamic/private';

import type { RequestHandler } from './$types';

const BACKEND_TARGET = env.SURVEY_API_PROXY_TARGET ?? 'http://127.0.0.1:8100';
const BODYLESS_METHODS = new Set(['GET', 'HEAD']);

async function proxy(request: Request, url: URL, path: string): Promise<Response> {
  const upstreamUrl = new URL(`/api/${path}`, BACKEND_TARGET);
  upstreamUrl.search = url.search;

  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.set('x-survey-public-base-url', url.origin);

  const body = BODYLESS_METHODS.has(request.method) ? undefined : await request.arrayBuffer();
  const upstream = await fetch(upstreamUrl, {
    method: request.method,
    headers,
    body,
    redirect: 'manual',
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: new Headers(upstream.headers),
  });
}

const handler: RequestHandler = async ({ params, request, url }) => {
  return proxy(request, url, params.path ?? '');
};

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
export const OPTIONS = handler;
export const HEAD = handler;
