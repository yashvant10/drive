import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { Header, Footer } from "@/components/site";
import { Portal } from "@/components/portal";
import { workspaceHome, type Profile, type Role } from "@/lib/api";

const routes: Record<Role, string[]> = {
  owner:["dashboard"],
  customer: ["dashboard", "book", "vehicles", "addresses", "bookings", "payments", "receipts", "reviews", "notifications", "support", "settings"],
  driver: ["dashboard", "onboarding", "verification", "availability", "requests", "active-trip", "trips", "earnings", "skill-passport", "documents", "notifications", "support", "profile"],
  admin: ["dashboard", "customers", "drivers", "verifications", "bookings", "live-operations", "pricing", "commissions", "payments", "refunds", "payouts", "reports", "incidents", "reviews", "support", "notifications", "staff", "audit-logs", "settings"],
};

const scopedRoutes = {
  operations:["dashboard", "customers", "drivers", "verifications", "bookings", "live-operations", "notifications"],
  finance:["dashboard","bookings","pricing","commissions","payments","refunds","payouts","reports","notifications"],
  support:["dashboard","customers","bookings","incidents","reviews","support","notifications"],
};

export default async function Workspace({params, searchParams}: {
  params: Promise<{role:string;section?:string[]}>; searchParams: Promise<{plan?:string}>;
}) {
  const {role, section = []} = await params;
  const {plan} = await searchParams;
  const [tab = "dashboard", id] = section;
  if (!Object.hasOwn(routes, role) || !routes[role as Role].includes(tab) || section.length > (["bookings", "trips"].includes(tab) ? 2 : 1)) notFound();
  const next = "/" + [role, ...section].join("/") + (tab === "book" && typeof plan === "string" ? "?plan=" + encodeURIComponent(plan) : "");
  const token = (await cookies()).get("drive_session");
  if (!token) redirect("/login?next=" + encodeURIComponent(next));
  const profile = await fetch((process.env.API_URL ?? "http://127.0.0.1:8000") + "/api/v1/auth/me", {
    cache:"no-store", headers:{cookie:"drive_session=" + encodeURIComponent(token.value)},
  });
  if (profile.status === 401) redirect("/login?next=" + encodeURIComponent(next));
  if (!profile.ok) throw new Error("The account service is unavailable.");
  const user: Profile = await profile.json();
  if (user.role !== role) redirect(workspaceHome(user.role));
  const tabs = user.role === "admin" && user.staff_scope ? scopedRoutes[user.staff_scope] : routes[user.role];
  if (!tabs.includes(tab)) redirect("/admin");
  return <><Header workspace={workspaceHome(user.role)} /><Portal user={user} tab={tab} id={id} tabs={tabs} plan={typeof plan === "string" ? plan : undefined} /><Footer /></>;
}
