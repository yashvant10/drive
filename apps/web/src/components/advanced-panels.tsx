"use client";

import Link from "next/link";
import Image from "next/image";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { api, date, money, send, statusText, type Booking, type Profile } from "@/lib/api";

type Value = string | number | boolean | null;
type Row = Record<string, Value> & {id: string};
type PageData = {rows: Row[]; has_more: boolean};

function useResource<T>(path: string, poll?:number) {
  return useQuery({queryKey:[path],queryFn:()=>api<T>(path),refetchInterval:poll});
}

function useTask() {
  const query = useQueryClient();
  const [busy,setBusy] = useState(false);
  const [message,setMessage] = useState("");
  const [failed,setFailed] = useState(false);
  async function execute(action:()=>Promise<unknown>, success = "Saved.") {
    setBusy(true);
    setMessage("");
    setFailed(false);
    try {
      await action();
      await query.invalidateQueries();
      setMessage(success);
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : "Please try again.");
      await query.invalidateQueries();
    } finally {setBusy(false);}
  }
  return {busy,execute,message,failed};
}

function Feedback({task}: {task:ReturnType<typeof useTask>}) {
  return task.message ? <p role={task.failed ? "alert" : "status"} className={task.failed ? "error" : "notice"}>{task.message}</p> : null;
}

function Loading({query}: {query:{isPending:boolean;error:Error|null}}) {
  if (query.isPending) return <p role="status">Loading…</p>;
  if (query.error) return <p role="alert" className="error">{query.error.message}</p>;
  return null;
}

function values(event:FormEvent<HTMLFormElement>): FormData {
  event.preventDefault();
  return new FormData(event.currentTarget);
}

const columnNames: Record<string,string> = {id:"Reference", booking_id:"Booking", driver_id:"Driver", amount_paise:"Amount", created_at:"Recorded", starts_at:"Pickup time", licence_expiry:"Licence expiry", actor_id:"Actor", subject_id:"Subject", provider_refund_id:"Razorpay refund"};
function label(key:string) {
  return columnNames[key] ?? key[0].toUpperCase()+key.slice(1).replaceAll("_"," ");
}

function display(key:string,value:Value) {
  if (value === null) return "—";
  if (key.endsWith("_paise") && typeof value === "number") return money(value);
  if ((key.endsWith("_at") || key === "licence_expiry") && typeof value === "string") return date(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (key === "status") return <span className="badge">{statusText(String(value))}</span>;
  if (key === "booking_id") return <Link href={"/admin/bookings/"+value} className="text-link">{value}</Link>;
  return value;
}

function Table({rows,columns,action}: {rows:Row[];columns:string[];action?:(row:Row)=>ReactNode}) {
  if (!rows.length) return <p className="notice">No records found.</p>;
  return <div className="table-scroll" tabIndex={0} role="region" aria-label="Records table"><table>
    <thead><tr>{columns.map(key=><th key={key} scope="col">{label(key)}</th>)}{action && <th scope="col">Actions</th>}</tr></thead>
    <tbody>{rows.map(row=><tr key={row.id}>{columns.map(key=><td key={key}>{display(key,row[key]??null)}</td>)}{action && <td>{action(row)}</td>}</tr>)}</tbody>
  </table></div>;
}

const directories: Record<string,string[]> = {
  customers:["name","email","disabled_at"],
  drivers:["name","email","approved","online","area","licence_expiry"],
  bookings:["id","pickup","status","fare_paise","starts_at"],
  staff:["name","email","role","staff_scope"],
  "live-operations":["id","area","status","starts_at"],
  payments:["booking_id","kind","amount_paise","status","created_at"],
  reviews:["booking_id","rating","comment","created_at"],
  incidents:["booking_id","description","status","created_at"],
  "audit-logs":["action","actor_id","subject_id","created_at"],
};

function Directory({section}: {section:string}) {
  const [draft,setDraft] = useState("");
  const [search,setSearch] = useState("");
  const [page,setPage] = useState(1);
  const [newest,setNewest] = useState(true);
  const parameters = new URLSearchParams({q:search,newest:String(newest)});
  const base = "/admin/directory/"+section+"?"+parameters;
  const data = useResource<PageData>(base+"&page="+page,section==="live-operations"?10000:undefined);
  const task = useTask();
  const actions: Record<string,(row:Row)=>ReactNode> = {
    customers:row=><CustomerAccessButton row={row} />,
    staff:row=><form className="form" onSubmit={event=>{
      const fields=values(event);
      void task.execute(()=>send("/admin/staff/"+row.id+"/scope",Object.fromEntries(fields),"PUT"),"Staff access updated.");
    }}><label>Access<select required name="scope" defaultValue={String(row.staff_scope??"")}><option value="" disabled>Full administrator</option><option value="operations">Operations</option><option value="finance">Finance</option><option value="support">Support</option></select></label><button className="button compact secondary" disabled={task.busy}>Update access</button></form>,
    drivers:row=><>{row.approved && <button className="button compact secondary" disabled={task.busy} onClick={()=>{
      if (window.confirm("Suspend this driver and take them offline?")) void task.execute(()=>send("/admin/drivers/"+row.id+"/suspend"));
    }}>Suspend</button>}<PayoutAccount row={row} /></>,
    incidents:row=>row.status !== "CLOSED" && <div className="flex flex-wrap gap-2">
      {row.status!=="ESCALATED" && <button className="button compact secondary" disabled={task.busy} onClick={()=>void task.execute(()=>send("/admin/incidents/"+row.id+"/escalate"))}>Escalate internally</button>}
      <button className="button compact secondary" disabled={task.busy} onClick={()=>void task.execute(()=>send("/admin/incidents/"+row.id+"/close"))}>Close incident</button>
    </div>,
    bookings:row=><Link className="text-link" href={"/admin/bookings/"+row.id}>Inspect booking</Link>,
    "live-operations":row=><Link className="text-link" href={"/admin/bookings/"+row.id}>Inspect booking</Link>,
    payments:row=>row.status === "CAPTURED" && <Link href={"/admin/refunds?payment="+row.id} className="text-link">Refund options</Link>,
  };
  return <div className="card">
    <form className="table-toolbar" onSubmit={event=>{event.preventDefault();setSearch(draft.trim());setPage(1);}}>
      <label>Search<input value={draft} maxLength={100} onChange={event=>setDraft(event.target.value)} placeholder="Search records" /></label>
      <label>Order<select value={String(newest)} onChange={event=>{setNewest(event.target.value === "true");setPage(1);}}><option value="true">Newest first</option><option value="false">Oldest first</option></select></label>
      <button className="button compact">Search</button>
      <a className="button compact secondary" href={"/api/v1"+base+"&export=true"}>Export CSV</a>
    </form>
    <Loading query={data} /><Feedback task={task} />
    {data.data && <Table rows={data.data.rows} columns={directories[section]} action={actions[section]} />}
    {data.data && <div className="table-toolbar mt-4"><button className="button compact secondary" onClick={()=>setPage(page-1)} disabled={page===1}>Previous</button><span>Page {page}</span><button className="button compact secondary" onClick={()=>setPage(page+1)} disabled={!data.data.has_more}>Next</button></div>}
  </div>;
}

function CustomerAccessButton({row}: {row:Row}) {
  const profile=useResource<Profile>("/auth/me");
  const task=useTask();
  if (!profile.data || (profile.data.staff_scope && profile.data.staff_scope!=="operations")) return null;
  const suspended=!!row.disabled_at;
  return <><button className="button compact secondary" disabled={task.busy} onClick={()=>{
    if(window.confirm(suspended?"Restore this customer’s access?":"Suspend this customer and end their sessions?"))
      void task.execute(()=>send("/admin/customers/"+row.id+"/access",{suspended:!suspended},"PUT"));
  }}>{suspended?"Restore access":"Suspend account"}</button><Feedback task={task} /></>;
}

function Addresses() {
  const data = useResource<Row[]>("/customers/addresses");
  const task = useTask();
  return <div className="card"><Loading query={data} />
    {data.data?.length === 0 && <p>No saved addresses.</p>}
    {data.data?.map(row=><div key={row.id} className="record"><div><strong>{row.label}</strong><p>{row.address}</p></div><button className="button compact secondary" disabled={task.busy} onClick={()=>void task.execute(()=>send("/customers/addresses/"+row.id,undefined,"DELETE"),"Address removed.")}>Remove</button></div>)}
    <form className="form" onSubmit={event=>{const data=values(event);const form=event.currentTarget;void task.execute(async()=>{await send("/customers/addresses",Object.fromEntries(data));form.reset();});}}>
      <label>Label<input name="label" required minLength={2} maxLength={80} placeholder="Home" /></label>
      <label>Street address<textarea name="address" required minLength={5} maxLength={250} /></label>
      <button className="button" disabled={task.busy}>Save address</button>
    </form><Feedback task={task} />
  </div>;
}

function Reviews() {
  const data = useResource<Row[]>("/reviews");
  const bookings = useResource<Booking[]>("/bookings");
  const task = useTask();
  const eligible = bookings.data?.filter(item=>item.status === "COMPLETED" && !data.data?.some(review=>review.booking_id===item.id));
  return <div className="card"><Loading query={data} /><Loading query={bookings} />
    {data.data?.map(row=><div className="record" key={row.id}><div><strong>{row.rating} / 5</strong><p>{row.comment}</p></div><Link className="text-link" href={"/customer/bookings/"+row.booking_id}>View booking</Link></div>)}
    {bookings.data && data.data && !eligible?.length && <p className="notice">You have no completed trips awaiting a review.</p>}
    {!!eligible?.length && <form className="form" onSubmit={event=>{const fields=values(event);void task.execute(()=>send("/reviews",{...Object.fromEntries(fields),rating:Number(fields.get("rating"))}));}}>
      <label>Completed trip<select name="booking_id">{eligible.map(item=><option key={item.id} value={item.id}>{item.pickup} · {date(item.starts_at)}</option>)}</select></label>
      <label>Rating<select name="rating">{[5,4,3,2,1].map(rating=><option key={rating}>{rating}</option>)}</select></label>
      <label>Comment<textarea name="comment" maxLength={1200} /></label>
      <button className="button" disabled={task.busy}>Submit review</button>
    </form>}<Feedback task={task} />
  </div>;
}

function Receipts() {
  const data = useResource<Row[]>("/customers/receipts");
  return <div className="card"><Loading query={data} />
    {data.data?.length === 0 && <p>No receipts. A receipt is available after a payment is captured.</p>}
    {data.data?.map(row=><div className="record" key={row.id}><div><strong>{money(Number(row.amount_paise))}</strong><p>{statusText(String(row.kind))} · {row.reference}</p></div>
      <a className="button compact secondary" href={"/api/v1/customers/receipts/"+row.id}>Download receipt</a>
    </div>)}
  </div>;
}

type Passport = {experience:{years:number;languages:string;qualifications:string;emergency_contact:string}|null; licence_current:boolean;licence_reviewed_until:string|null;verified_categories:string|null;completed_trips:number;review_count:number;average_rating:number|null};
function Skills({onboarding}: {onboarding:boolean}) {
  const data = useResource<Passport>("/drivers/skill-passport");
  const task = useTask();
  const item = data.data;
  return <><div className="card"><h3>{onboarding ? "Get ready to drive" : "Verified platform activity"}</h3><Loading query={data} />
    {item && <><div className="record"><span>Driving licence</span><strong>{item.licence_current ? "Current and approved" : "Approval required"}</strong></div>
    {item.licence_current && item.licence_reviewed_until && <p>Review valid until {date(item.licence_reviewed_until)}</p>}
    {item.verified_categories && <div className="record"><span>Licence categories reviewed</span><strong>{item.verified_categories.split(",").map(statusText).join(", ")}</strong></div>}
    <div className="record"><span>Completed trips</span><strong>{item.completed_trips}</strong></div>
    <div className="record"><span>Customer rating</span><strong>{item.average_rating === null ? "No reviews yet" : item.average_rating+" / 5 ("+item.review_count+")"}</strong></div>
    <Link href="/driver/documents" className="text-link">Manage licence documents</Link></>}
  </div>{item && <div className="card"><h3>Self-reported experience</h3><form className="form" onSubmit={event=>{
    const fields=values(event);void task.execute(()=>send("/drivers/skill-passport",{...Object.fromEntries(fields),years:Number(fields.get("years")),consent:fields.has("consent")},"PUT"));
  }}>
    <label>Years of experience<input name="years" type="number" min={0} max={70} required defaultValue={item.experience?.years} /></label>
    <label>Languages<input name="languages" minLength={2} maxLength={150} required defaultValue={item.experience?.languages} /></label>
    <label>Training and qualifications<textarea name="qualifications" maxLength={1500} defaultValue={item.experience?.qualifications} /></label>
    <label>Emergency contact number<input name="emergency_contact" type="tel" required defaultValue={item.experience?.emergency_contact} /></label>
    <label className="row"><input name="consent" type="checkbox" required /> I confirm these details are accurate and consent to their storage.</label>
    <button className="button" disabled={task.busy}>Save experience</button>
  </form><Feedback task={task} /></div>}{onboarding && <DriverPhotoForm />}</>;
}

function Notifications({admin}: {admin:boolean}) {
  const data = useResource<Row[]>("/notifications");
  const task = useTask();
  const preferences = useResource<{email:boolean;sms:boolean;email_configured:boolean;sms_configured:boolean;sms_available:boolean}>("/notifications/preferences");
  const profile = useResource<Profile>("/auth/me");
  const canInspect = admin && profile.data?.role==="admin" && !profile.data.staff_scope;
  const deliveries = useQuery({queryKey:["/admin/notifications/deliveries"],queryFn:()=>api<Row[]>("/admin/notifications/deliveries"),enabled:canInspect});
  const channels = preferences.data;
  return <><div className="card"><Loading query={data} />
    {data.data?.length === 0 && <p>No notifications yet.</p>}
    {data.data?.map(row=><div className="record" key={row.id}><div><strong>{row.message}</strong><p>{date(String(row.created_at))}</p></div>
    {row.read ? <span className="badge">Read</span> : <button className="button compact secondary" disabled={task.busy} onClick={()=>void task.execute(()=>send("/notifications/"+row.id+"/read"),"Marked as read.")}>Mark as read</button>}</div>)}
    <Feedback task={task} />
  </div><div className="card"><h3>Notification preferences</h3><Loading query={preferences} />
    {channels && <form className="form" onSubmit={event=>{
      const fields=values(event);
      void task.execute(()=>send("/notifications/preferences",{email:channels.email_configured?fields.has("email"):channels.email,sms:channels.sms_configured&&channels.sms_available?fields.has("sms"):channels.sms},"PUT"));
    }}>
      <label className="row"><input type="checkbox" name="email" defaultChecked={channels.email} disabled={!channels.email_configured} /> Email updates</label>
      <label className="row"><input type="checkbox" name="sms" defaultChecked={channels.sms} disabled={!channels.sms_configured||!channels.sms_available} /> SMS updates to my verified number</label>
      {!channels.sms_available && <p>Verify your phone in your profile before enabling SMS.</p>}
      {(!channels.email_configured || !channels.sms_configured) && <p>Some delivery channels are unavailable in this environment.</p>}
      <button className="button compact" disabled={task.busy||(!channels.email_configured&&!channels.sms_configured)}>Save preferences</button>
    </form>}
  </div>{canInspect && <div className="card"><h3>External delivery log</h3><Loading query={deliveries} />{deliveries.data && <Table rows={deliveries.data} columns={["channel","status","provider_ref","created_at"]} />}</div>}</>;
}

function RateSettings({commission}: {commission:boolean}) {
  const data = useResource<Record<string,number>>("/admin/pricing");
  const task = useTask();
  const keys = commission ? ["commission_bps"] : ["base","hourly","half_day","full_day","extra_hour","waiting_hour","night","pickup_allowance","tax_bps","cancellation"];
  return <div className="card"><p>{commission ? "Set the platform commission in basis points. 100 basis points equal 1%." : "Set prices in paise. New booking requests use this rate card."}</p><Loading query={data} />
    {data.data && <form className="form" onSubmit={event=>{const fields=values(event);void task.execute(()=>send("/admin/"+(commission?"commissions":"pricing"),Object.fromEntries([...fields].map(([key,value])=>[key,Number(value)])),"PUT"));}}>
      {keys.map(key=><label key={key}>{key === "commission_bps" ? "Commission (basis points)" : key === "tax_bps" ? "Tax (basis points)" : label(key)+" (paise)"}<input type="number" min={["hourly","half_day","full_day"].includes(key)?1:0} max={key.endsWith("_bps")?10000:["half_day","full_day"].includes(key)?10000000:1000000} name={key} defaultValue={data.data[key]} required /></label>)}
      <button className="button" disabled={task.busy}>Save {commission ? "commission" : "rate card"}</button>
    </form>}<Feedback task={task} />
  </div>;
}

function Refunds() {
  const list = useResource<Row[]>("/admin/refunds");
  const settings = useResource<Record<string,Value>>("/admin/refunds/configuration");
  const task = useTask();
  const selected = typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("payment") ?? "";
  const enabled = settings.data?.online_checkout_configured === true;
  return <div className="card"><Loading query={list} /><Loading query={settings} />
    {settings.data && !enabled && <p>Razorpay must be configured before issuing refunds.</p>}
    {list.data && <Table rows={list.data} columns={["payment_id","amount_paise","status","provider_refund_id"]} action={row=>enabled && row.status !== "PROCESSED" && <form className="form" onSubmit={event=>{
      const fields=values(event);void task.execute(()=>send("/admin/refunds/"+row.id+"/reconcile",{reference:fields.get("reference")}));
    }}><label>Provider refund reference<input name="reference" required pattern="rfnd_[A-Za-z0-9]+" defaultValue={String(row.provider_refund_id??"")} /></label><button className="button compact secondary" disabled={task.busy}>Reconcile</button></form>} />}
    {enabled && <form className="form" onSubmit={event=>{
      const fields=values(event);if (window.confirm("Issue a full refund to the original payment method?")) void task.execute(()=>send("/admin/refunds/"+fields.get("payment")), "Refund request recorded. Check the status above.");
    }}><label>Captured payment reference<input name="payment" required defaultValue={selected} /></label><button className="button" disabled={task.busy}>Issue full refund</button></form>}
    <Feedback task={task} />
  </div>;
}

function PayoutAccount({row}: {row:Row}) {
  const profile = useResource<Profile>("/auth/me");
  const configuration = useQuery({queryKey:["/admin/payouts/configuration"],queryFn:()=>api<{configured:boolean}>("/admin/payouts/configuration"),enabled:profile.data?.role==="admin" && !profile.data.staff_scope});
  const task=useTask();
  if (!configuration.data?.configured) return null;
  return <form className="form" onSubmit={event=>{
    const fields=values(event);
    if (window.confirm("Use this verified RazorpayX fund account for future payouts to this driver?")) {
      void task.execute(()=>send("/admin/drivers/"+row.id+"/payout-account",Object.fromEntries(fields),"PUT"),"Payout account saved.");
    }
  }}><label>Provider fund account<input name="reference" required pattern="fa_[A-Za-z0-9]+" /></label>
    <button className="button compact secondary" disabled={task.busy}>Set payout account</button><Feedback task={task} />
  </form>;
}

function Payouts() {
  const data = useResource<Row[]>("/admin/payouts");
  const configuration = useResource<{configured:boolean}>("/admin/payouts/configuration");
  const task = useTask();
  return <div className="card"><p>Review accrued driver earnings tied to captured payments.</p><Loading query={data} />
    {configuration.data && !configuration.data.configured && <p>RazorpayX is unconfigured. A review request does not transfer funds.</p>}
    {data.data && <Table rows={data.data} columns={["booking_id","driver_id","amount_paise","status","provider_payout_id"]} action={row=><>
      {row.status==="UNSETTLED" && <button className="button compact secondary" disabled={task.busy} onClick={()=>void task.execute(()=>send("/admin/payouts/"+row.id),"Payout review requested.")}>Request payout review</button>}
      {configuration.data?.configured && ["PENDING_REVIEW","SUBMITTING"].includes(String(row.status)) && <button className="button compact" disabled={task.busy} onClick={()=>{
        if(window.confirm("Submit "+money(Number(row.amount_paise))+" to the driver's verified RazorpayX fund account?"))
          void task.execute(()=>send("/admin/payouts/"+row.id+"/submit"),"Provider response recorded.");
      }}>{row.status==="SUBMITTING"?"Retry same payout":"Submit payout"}</button>}
      {configuration.data?.configured && !["UNSETTLED","PENDING_REVIEW"].includes(String(row.status)) && <form className="form" onSubmit={event=>{
        const fields=values(event);void task.execute(()=>send("/admin/payouts/"+row.id+"/reconcile",Object.fromEntries(fields)),"Provider status reconciled.");
      }}><label>Provider payout reference<input name="reference" required pattern="pout_[A-Za-z0-9]+" defaultValue={String(row.provider_payout_id??"")} /></label>
        <button className="button compact secondary" disabled={task.busy}>Reconcile payout</button></form>}
    </>} />}
    <Feedback task={task} />
  </div>;
}

function AdminSettings({reports}: {reports:boolean}) {
  const path = reports ? "/admin/financials" : "/admin/settings";
  const data = useResource<Record<string,Value>>(path);
  return <div className="card"><Loading query={data} />
    {Object.entries(data.data??{}).map(([key,value])=><div className="record" key={key}><span>{label(key)}</span><strong>{reports ? money(Number(value)) : typeof value === "boolean" ? (value?"Yes":"No") : value}</strong></div>)}
    {reports && <Link prefetch={false} className="button secondary mt-4" href="/api/v1/admin/directory/payments?export=true" download>Download payments CSV</Link>}
  </div>;
}

function DriverPhotoForm() {
  const status=useResource<{has_photo:boolean}>("/drivers/avatar-status");
  const task=useTask();
  const [version,setVersion]=useState(0);
  return <div className="card"><h3>Driver profile photo</h3><Loading query={status} />
    <p>Assigned customers can see your photo in their booking.</p>
    {status.data?.has_photo && <Image unoptimized className="rounded-lg mt-3" src={"/api/v1/drivers/avatar?v="+version} width={96} height={96} alt="Your driver profile" />}
    <form className="form" onSubmit={event=>{
      const fields=values(event);const form=event.currentTarget;
      void task.execute(async()=>{await api("/drivers/avatar",{method:"PUT",body:fields});setVersion(version+1);form.reset();},"Profile photo saved.");
    }}><label>Profile photo (max 3 MB)<input name="photo" type="file" accept="image/jpeg,image/png,image/webp" required /></label>
    <button className="button compact" disabled={task.busy}>Upload photo</button></form>
    {status.data?.has_photo && <button className="button compact secondary" disabled={task.busy} onClick={()=>void task.execute(()=>send("/drivers/avatar",undefined,"DELETE"),"Profile photo removed.")}>Remove photo</button>}
    <Feedback task={task} />
  </div>;
}

export function ProfileSettings({user}: {user:Profile}) {
  const task = useTask();
  return <><div className="card"><p>{user.email} · {user.role}</p><form className="form" onSubmit={event=>{
    const fields=values(event);void task.execute(()=>send("/auth/me",Object.fromEntries(fields),"PATCH"));
  }}><label>Full name<input name="name" defaultValue={user.name} required minLength={2} maxLength={100} /></label><button className="button" disabled={task.busy}>Save profile</button></form><Feedback task={task} /></div><PhoneVerification />{user.role==="driver" && <DriverPhotoForm />}</>;
}

export function AdvancedPanel({role,tab}: {role:string;tab:string}) {
  if (role === "admin" && Object.hasOwn(directories,tab)) return <Directory key={tab} section={tab} />;
  switch(tab) {
    case "addresses": return <Addresses />;
    case "reviews": return <Reviews />;
    case "receipts": return <Receipts />;
    case "onboarding": return <Skills onboarding />;
    case "skill-passport": return <Skills onboarding={false} />;
    case "notifications": return <Notifications admin={role === "admin"} />;
    case "pricing": return <RateSettings commission={false} />;
    case "commissions": return <RateSettings commission />;
    case "refunds": return <Refunds />;
    case "payouts": return <Payouts />;
    case "reports": return <AdminSettings reports />;
    case "settings": return <AdminSettings reports={false} />;
    default: return null;
  }
}

export function BookingSafety({booking,customer}: {booking:Booking;customer:boolean}) {
  const task = useTask();
  const [share,setShare] = useState("");
  const shares = useQuery({queryKey:["/family-shares/"+booking.id],queryFn:()=>api<Row[]>("/family-shares/"+booking.id),enabled:customer});
  const incidents=useResource<Row[]>("/incidents/"+booking.id,10000);
  const assigned=["ASSIGNED","CONFIRMED","DRIVER_EN_ROUTE","DRIVER_ARRIVED","IN_PROGRESS"].includes(booking.status);
  return <section className="mt-6" aria-label="Trip safety">
    <h3>Trip safety</h3><p>For immediate danger, call <a href="tel:112" className="text-link">112</a>. Reports go to Drivewell support.</p>
    {assigned && <button className="button secondary mt-3" disabled={task.busy} onClick={()=>{
      if(window.confirm("Send an urgent alert to Drivewell Support? For emergency services call 112."))
        void task.execute(()=>send("/incidents/"+booking.id+"/sos"),"Urgent alert recorded for Drivewell Support.");
    }}>Send urgent safety alert</button>}
    {incidents.data?.map(item=><div className="record" key={item.id}><span>{item.description}</span><span className="badge">{statusText(String(item.status))}</span></div>)}
    <form className="form" onSubmit={event=>{const fields=values(event);void task.execute(()=>send("/incidents",{booking_id:booking.id,description:fields.get("description")}),"Incident reported to Drivewell.");}}>
      <label>What happened?<textarea name="description" required minLength={3} maxLength={2000} /></label><button className="button secondary" disabled={task.busy}>Report an incident</button>
    </form>
    {customer && <><h3>Share your trip</h3><p>A share link shows the trip status and any location shared by the driver. It expires in four hours or when the trip ends.</p>
      {["DRIVER_EN_ROUTE","DRIVER_ARRIVED","IN_PROGRESS"].includes(booking.status) && <button className="button compact secondary" disabled={task.busy} onClick={()=>void task.execute(async()=>{
        const item=await send<{token:string}>("/family-shares/"+booking.id);
        setShare(window.location.origin+"/trip-share#"+item.token);
      },"Link created. Share it only with someone you trust.")}>Create share link</button>}
      {share && <label>Trip link<input value={share} readOnly onFocus={event=>event.target.select()} /></label>}
      {shares.data?.filter(row=>!row.revoked).map(row=><div className="record" key={row.id}><span>Expires {date(String(row.expires_at))}</span>
        <button className="button compact secondary" disabled={task.busy} onClick={()=>void task.execute(async()=>{await send("/family-shares/"+row.id,undefined,"DELETE");setShare("");},"Link revoked.")}>Revoke link</button></div>)}
    </>}<Feedback task={task} />
  </section>;
}

function PhoneVerification() {
  const data = useResource<{configured:boolean;verified_phone:string|null;pending_phone:string|null}>("/auth/phone");
  const task = useTask();
  return <div className="card mt-4"><h3>Phone verification</h3><Loading query={data} />
    {data.data?.verified_phone && <p>Verified number {data.data.verified_phone}</p>}
    {data.data && !data.data.configured && <p>SMS verification is unavailable in this environment.</p>}
    {data.data?.configured && <form className="form" onSubmit={event=>{
      const fields=values(event);void task.execute(()=>send("/auth/phone/send",Object.fromEntries(fields)),"The provider accepted the SMS request.");
    }}><label>Phone number with country code<input name="phone" type="tel" placeholder="+91…" autoComplete="tel" required /></label>
      <button className="button secondary" disabled={task.busy}>Request verification code</button>
    </form>}
    {data.data?.configured && data.data.pending_phone && <form className="form" onSubmit={event=>{
      const fields=values(event);void task.execute(()=>send("/auth/phone/verify",Object.fromEntries(fields)),"Phone number verified.");
    }}>
      <label>Code sent to {data.data.pending_phone}<input name="code" inputMode="numeric" autoComplete="one-time-code" required pattern="[0-9]{4,10}" /></label>
      <button className="button" disabled={task.busy}>Verify number</button>
    </form>}<Feedback task={task} />
  </div>;
}
