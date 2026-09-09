export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    cache: "no-store",
    signal: AbortSignal.timeout(8000),
    ...(body !== undefined
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {}),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `API request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}
export const money = (value: string | number | null | undefined) =>
  value == null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      }).format(Number(value));
export const pct = (value: string | number | null | undefined) =>
  value == null ? "—" : `${(Number(value) * 100).toFixed(2)}%`;
export const time = (value: string) =>
  new Date(value).toLocaleTimeString("en-US", { hour12: false });
