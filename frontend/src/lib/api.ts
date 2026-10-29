export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export type Fetcher = <T = unknown>(path: string, opts?: { method?: string; body?: unknown; form?: FormData }) => Promise<T>

export function makeApi(extraHeaders: () => Record<string, string> = () => ({})): Fetcher {
  return async function api<T>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
    const headers: Record<string, string> = { 'X-Requested-With': 'atrium', ...extraHeaders() }
    let body: BodyInit | undefined
    if (opts.form) body = opts.form
    else if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json'
      body = JSON.stringify(opts.body)
    }
    const res = await fetch(path, { method: opts.method ?? (body ? 'POST' : 'GET'), headers, body, credentials: 'same-origin' })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const j = await res.json()
        detail = typeof j.detail === 'string' ? j.detail : detail
      } catch {}
      throw new ApiError(res.status, detail)
    }
    const type = res.headers.get('content-type') ?? ''
    return (type.includes('application/json') ? await res.json() : await res.text()) as T
  }
}

export const api = makeApi()

export function socketUrl(path: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}${path}`
}
