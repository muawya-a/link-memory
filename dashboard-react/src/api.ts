export type JsonRecord = Record<string, unknown>;

export interface ServiceStatus { ok?: boolean; status?: string; name?: string; [key: string]: unknown }
export interface GatewayStatus { ok?: boolean; services?: Record<string, ServiceStatus>; [key: string]: unknown }
export interface MetricData { captures?: number; saved?: number; rejected?: number; failed?: number; redactions?: number; review?: number; latency_ms?: number; health?: string; [key: string]: unknown }
export interface Capture { id?: string; status?: string; source?: string; conversation_id?: string; saved_count?: number; rejected_count?: number; message_count?: number; duration_ms?: number; error?: string; created_at?: string; privacy_redactions?: number }
export interface RetryItem { provider?: string; memory_id?: string; attempts?: number; next_retry_at?: string; last_error?: string }
export interface Memory { id: string; text: string; type?: string; source?: string; confidence?: number; date?: string; conversation_id?: string }
export interface SearchResponse { results?: Memory[]; memories?: Memory[]; meta?: JsonRecord }

const DEFAULT_API = 'http://127.0.0.1:18000';

function isLoopback(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (host === 'localhost' || host === '::1') return true;
  if (!/^127(?:\.\d{1,3}){3}$/.test(host)) return false;
  return host.split('.').slice(1).every((part) => Number(part) <= 255);
}

function defaultApiBase(): string {
  if (typeof window === 'undefined') return DEFAULT_API;
  const page = new URL(window.location.href);
  return isLoopback(page.hostname) ? DEFAULT_API : page.origin;
}

function normalizeApiBase(value: string): string {
  const page = new URL(window.location.href);
  let target: URL;
  try {
    target = new URL(value.trim());
  } catch {
    throw new Error('Invalid service address.');
  }
  if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password || target.search || target.hash) {
    throw new Error('Invalid service address.');
  }

  const pageIsLoopback = isLoopback(page.hostname);
  const targetIsLoopback = isLoopback(target.hostname);
  const sameOrigin = target.origin === page.origin;
  const allowed = sameOrigin || (pageIsLoopback && targetIsLoopback);
  const secureRemoteOrigin = target.protocol === 'https:' || (pageIsLoopback && targetIsLoopback);
  if (!allowed || !secureRemoteOrigin) {
    throw new Error('Service address must be this site or a local loopback address.');
  }

  return `${target.origin}${target.pathname}`.replace(/\/+$/, '') || target.origin;
}

export function apiBase(): string {
  return localStorage.getItem('link-memory-api') || defaultApiBase();
}

export function setApiBase(value: string): void {
  localStorage.setItem('link-memory-api', normalizeApiBase(value || defaultApiBase()));
}

export function setApiKey(value: string): void {
  if (value) sessionStorage.setItem('link-memory-api-key', value);
  else sessionStorage.removeItem('link-memory-api-key');
}

export async function api<T extends JsonRecord | unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const base = normalizeApiBase(apiBase());
  const apiKey = sessionStorage.getItem('link-memory-api-key') || '';
  const response = await fetch(`${base}${path}`, {
    ...init,
    redirect: 'error',
    headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}), ...(init.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const payload = body as JsonRecord;
    const error = typeof payload.error === 'string' ? payload.error : `HTTP ${response.status}`;
    const detail = typeof payload.detail === 'string' ? payload.detail.trim() : '';
    throw new Error(detail && detail !== error ? `${error}: ${detail}` : error);
  }
  return body as T;
}

export function post<T extends JsonRecord | unknown>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: 'POST', body: JSON.stringify(body) });
}
