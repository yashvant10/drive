export type Role = "customer" | "driver" | "admin" | "owner";

export function workspaceHome(role:Role) {
  return role==="admin" || role==="owner" ? "/"+role : "/"+role+"/dashboard";
}
export type Profile = {id: string; name: string; email: string; role: Role; staff_scope?: "operations" | "finance" | "support" | null};
export type Vehicle = {id: string; label: string; transmission: string; category: string};
export type Booking = {id: string; area: string; pickup: string; destination: string; status: string; fare_paise: number; starts_at: string; hours: number; driver_id: string | null; driver_name: string | null; driver_has_photo: boolean; pickup_latitude: number | null; pickup_longitude: number | null};
export type Quote = {overage_hour_paise:number; cancellation_paise:number; quote_id: string; expires_at: string; base_paise: number; service_paise: number; extra_paise: number; waiting_paise: number; night_paise: number; pickup_allowance_paise: number; tax_paise: number; total_paise: number; hours: number; eligible_driver_available: boolean};
export type Driver = {approved: boolean; online: boolean; area: string; transmission: string; categories: string; schedule_only: boolean; dispatch_at: string | null};
export type Offer = Pick<Booking, "id" | "area" | "hours" | "starts_at" | "fare_paise"> & {transmission: string; expires_at: string; category: string; distance_km: number | null};
export type Ticket = {id: string; message: string; status: string};

export class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    ...options, headers: { ...(options?.body && !(options.body instanceof FormData) ? {"Content-Type": "application/json"} : {}), ...options?.headers },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(response.status, typeof data?.detail === "string" ? data.detail : typeof data?.detail?.[0]?.msg === "string" ? data.detail[0].msg : "The service could not complete this request.");
  }
  return response.status === 204 ? undefined as T : response.json();
}

export function send<T>(path: string, data?: unknown, method = "POST") {
  return api<T>(path, {method, body: data === undefined ? undefined : JSON.stringify(data)});
}

export const money = (paise: number) => new Intl.NumberFormat("en-IN", {style:"currency", currency:"INR"}).format(paise / 100);
export const date = (value: string) => new Intl.DateTimeFormat("en-IN", { dateStyle:"medium", timeStyle:"short",timeZone:"Asia/Kolkata" }).format(new Date(value));
export const statusText = (value: string) => value.toLowerCase().replaceAll("_", " ");
