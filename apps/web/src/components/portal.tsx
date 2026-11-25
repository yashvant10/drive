"use client";
import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { OwnerOverview } from "./owner-overview";
import { TripMap, RouteDetails, type Point, type Route } from "./trip-map";
import { AdvancedPanel, BookingSafety, ProfileSettings } from "./advanced-panels";
import { ArrowRight, CarFront, LogOut } from "lucide-react";
import { api, date, money, send, statusText, workspaceHome, type Booking, type Driver, type Offer, type Profile, type Quote, type Ticket, type Vehicle } from "@/lib/api";

const labels: Record<string,string> = {dashboard:"Overview",book:"Book a driver",vehicles:"Vehicles",bookings:"Bookings",settings:"Settings",availability:"Availability",requests:"Requests",trips:"Trips",support:"Support",profile:"Profile",payments:"Payments",verification:"Licence verification",verifications:"Driver verification",earnings:"Earnings",addresses:"Saved addresses",receipts:"Receipts",reviews:"Reviews",notifications:"Notifications",onboarding:"Onboarding","active-trip":"Active trip","skill-passport":"Skill Passport",documents:"Documents",customers:"Customers",drivers:"Drivers","live-operations":"Live operations",pricing:"Pricing",commissions:"Commissions",refunds:"Refunds",payouts:"Payouts",reports:"Reports",incidents:"Safety incidents",staff:"Staff","audit-logs":"Audit logs"};

function useData<T>(path: string, poll?: number, enabled = true) {
  return useQuery({queryKey:[path],queryFn:()=>api<T>(path),refetchInterval:poll,enabled});
}

function State({pending,error}: {pending:boolean;error:Error|null}) {
  if (pending) return <p role="status" className="notice">Loading…</p>;
  if (error) return <p role="alert" className="error">{error.message}</p>;
  return null;
}

function useAction() {
  const query = useQueryClient();
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  async function run(action:()=>Promise<unknown>) {
    setBusy(true);
    setError("");
    try {await action(); await query.invalidateQueries();}
    catch (cause) {setError(cause instanceof Error ? cause.message : "Please try again.");}
    finally {setBusy(false);}
  }
  return {busy,run,error};
}

function ErrorMessage({error}: {error:string}) {
  return error ? <p className="error" role="alert">{error}</p> : null;
}

function Fields({children,onSubmit}: {children:ReactNode;onSubmit:(data:FormData,form:HTMLFormElement)=>void}) {
  function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(new FormData(event.currentTarget),event.currentTarget);
  }
  return <form className="form" onSubmit={submit}>{children}</form>;
}

function Badge({value}: {value:string}) {
  return <span className="badge">{statusText(value)}</span>;
}

const categories = [["sedan","Sedan"],["hatchback","Hatchback"],["suv","SUV"],["mpv","MPV"]];

function currentPosition() {
  return new Promise<{latitude:number;longitude:number}>((resolve,reject)=>{
    if (!navigator.geolocation) {reject(new Error("Location is unavailable in this browser."));return;}
    navigator.geolocation.getCurrentPosition(({coords})=>resolve({latitude:coords.latitude,longitude:coords.longitude}),
      error=>reject(new Error(error.message)),{enableHighAccuracy:true,timeout:12000});
  });
}

function VehiclePanel() {
  const data = useData<Vehicle[]>("/vehicles");
  const action = useAction();
  const [editing,setEditing] = useState<Vehicle|null>(null);
  return <div className="card"><h3>Saved vehicles</h3><State pending={data.isPending} error={data.error} />
    {data.data?.length === 0 && <p>Add your first vehicle to request a driver.</p>}
    {data.data?.map(vehicle => <div className="record" key={vehicle.id}><span>{vehicle.label}</span><Badge value={vehicle.category+" · "+vehicle.transmission} /><div className="flex gap-2">
      <button className="button compact secondary" type="button" onClick={()=>setEditing(vehicle)}>Edit</button>
      <button className="button compact secondary" type="button" disabled={action.busy} onClick={()=>{if(window.confirm("Remove this saved vehicle?")) void action.run(async()=>{await send("/vehicles/"+vehicle.id,undefined,"DELETE");if(editing?.id===vehicle.id)setEditing(null);});}}>Remove</button>
    </div></div>)}
    <Fields key={editing?.id??"new"} onSubmit={(fields,form)=>void action.run(async()=>{await send("/vehicles"+(editing?"/"+editing.id:""),Object.fromEntries(fields),editing?"PUT":"POST");form.reset();setEditing(null);})}>
      <label>Vehicle name<input name="label" defaultValue={editing?.label} placeholder="e.g. Honda City" required minLength={2} maxLength={100} /></label>
      <label>Vehicle category<select name="category" defaultValue={editing?.category??"sedan"}>{categories.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
      <label>Transmission<select name="transmission" defaultValue={editing?.transmission??"manual"}><option value="manual">Manual</option><option value="automatic">Automatic</option></select></label>
      <ErrorMessage error={action.error} /><button disabled={action.busy} className="button">{editing ? "Save vehicle" : "Add vehicle"}</button>{editing && <button className="button secondary" type="button" onClick={()=>setEditing(null)}>Cancel edit</button>}
    </Fields>
  </div>;
}

function BookingForm({plan}: {plan?:string}) {
  const vehicles = useData<Vehicle[]>("/vehicles");
  const addresses = useData<{id:string;address:string;label:string}[]>("/customers/addresses");
  const [pickup,setPickup] = useState("");
  const [destination,setDestination] = useState("");
  const [route,setRoute] = useState<Route|null>(null);
  const [pickupPoint,setPickupPoint] = useState<{latitude:number;longitude:number}|null>(null);
  const router = useRouter();
  const action = useAction();
  const routing = useAction();
  const [chosen,setChosen] = useState(["half-day","full-day"].includes(plan ?? "") ? plan! : "hourly");
  const [requested,setRequested] = useState<{quote:Quote; payload:Record<string,unknown>}|null>(null);
  return <div className="card"><h3>Trip details</h3><State pending={vehicles.isPending} error={vehicles.error} />
    {vehicles.data?.length === 0 && <p><Link className="text-link" href="/customer/vehicles"><CarFront size={18} /> Add a vehicle to continue</Link></p>}
    {!!vehicles.data?.length && <form className="form" onChange={()=>setRequested(null)} onSubmit={event=>{
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.currentTarget));
      const {schedule_date, ...rest} = values;
      const payload = {...rest, pickup_point:pickupPoint, hours:Number(values.hours || 2), extra_hours:Number(values.extra_hours||0), waiting_hours:Number(values.waiting_hours||0), starts_at:schedule_date ? String(schedule_date) + ":00+05:30" : null};
      void action.run(async()=>setRequested({quote:await send<Quote>("/fares/quote",payload),payload}));
    }}>
      <label>Vehicle<select name="vehicle_id">{vehicles.data.map(vehicle=><option value={vehicle.id} key={vehicle.id}>{vehicle.label} · {vehicle.transmission}</option>)}</select></label>
      {!!addresses.data?.length && <label>Use a saved pickup<select defaultValue="" onChange={event=>{if(event.target.value){setPickup(event.target.value);setPickupPoint(null);setRoute(null);}}}><option value="">Enter an address manually</option>{addresses.data.map(item=><option value={item.address} key={item.id}>{item.label}</option>)}</select></label>}
      <label>Pickup address in Bengaluru<input name="pickup" value={pickup} onChange={event=>{setPickup(event.target.value);setPickupPoint(null);setRoute(null);}} required minLength={5} maxLength={250} /></label>
      <label>Destination (optional)<input name="destination" maxLength={250} value={destination} onChange={event=>{setDestination(event.target.value);setRoute(null);}} /></label>
      <details className="booking-map-details"><summary>Set pickup on map or preview route</summary>
        <TripMap pickup={pickupPoint} route={route} onPick={point=>{setPickupPoint(point);setRequested(null);setRoute(null);}} />
        <div className="row">
          <button type="button" className="button compact secondary" disabled={action.busy} onClick={()=>void action.run(async()=>{setPickupPoint(await currentPosition());setRequested(null);setRoute(null);})}>Use my location as pickup pin</button>
          {pickupPoint && <button type="button" className="button compact secondary" onClick={()=>{setPickupPoint(null);setRequested(null);setRoute(null);}}>Remove pin</button>}
          <button type="button" className="button compact secondary" disabled={routing.busy || pickup.trim().length<5 || destination.trim().length<5} onClick={()=>void routing.run(async()=>setRoute(await send("/maps/preview",{pickup,destination,pickup_point:pickupPoint})))}>Preview driving route</button>
          {pickup && destination && <a className="text-link" href={"https://www.google.com/maps/dir/?api=1&origin="+encodeURIComponent(pickup)+"&destination="+encodeURIComponent(destination)} target="_blank" rel="noreferrer">Open route in Google Maps</a>}
        </div>
        {route && <RouteDetails route={route} />}
        <ErrorMessage error={routing.error} />
      </details>
      <label>Start time (India time, leave blank for now)<input name="schedule_date" type="datetime-local" /></label>
      <label>Booking duration<select name="plan" value={chosen} onChange={event=>setChosen(event.target.value)}><option value="hourly">Hourly</option><option value="half-day">Half day · 4 hours</option><option value="full-day">Full day · 8 hours</option></select></label>
      {chosen === "hourly" && <label>Hours<input name="hours" type="number" min={1} max={12} defaultValue={2} required /></label>}
      <details><summary>Additional time and planned waiting</summary><div className="grid gap-3 mt-3">
        <label>Additional driving hours<input type="number" name="extra_hours" min={0} max={4} defaultValue={0} required /></label>
        <label>Planned waiting hours<input type="number" name="waiting_hours" min={0} max={3} defaultValue={0} required /></label>
      </div></details>
      <label>Trip instructions (optional)<textarea name="instructions" maxLength={1000} rows={3} /></label>
      <ErrorMessage error={action.error} /><button className="button secondary" disabled={action.busy}>Get fare estimate</button>
    </form>}
    {requested && <section aria-label="Fare estimate">
      <div className="record"><span>Base charge</span><span>{money(requested.quote.base_paise)}</span></div>
      <div className="record"><span>Service charge</span><span>{money(requested.quote.service_paise)}</span></div>
      {([["Extra time","extra_paise"],["Planned waiting","waiting_paise"],["Night surcharge","night_paise"],["Pickup allowance","pickup_allowance_paise"],["Tax","tax_paise"]] as const).filter(([,key])=>requested.quote[key]>0).map(([label,key])=><div className="record" key={key}><span>{label}</span><span>{money(requested.quote[key])}</span></div>)}
      <p className="notice">Reserved duration {requested.quote.hours} hours</p>
      {requested.quote.overage_hour_paise>0 && <p>After a 15-minute grace period, actual overage costs {money(requested.quote.overage_hour_paise)} per started hour, capped at four additional hours.</p>}
      {requested.quote.cancellation_paise>0 && <p>Assigned driver cancellation fee: {money(requested.quote.cancellation_paise)} within 15 minutes of pickup or later, before arrival.</p>}
      <div className="record"><strong>Estimated total</strong><strong>{money(requested.quote.total_paise)}</strong></div>
      <p className="notice" role="status">{requested.quote.eligible_driver_available ? "An eligible driver is online. Assignment is pending until a driver accepts." : "No eligible driver is currently online for this time. You can still submit a request."}</p>
      <button className="button" disabled={action.busy} onClick={()=>void action.run(async()=>{const booking=await send<Booking>("/bookings",{...requested.payload,quote_id:requested.quote.quote_id});router.push("/customer/bookings/"+booking.id);})}>Submit booking request <ArrowRight size={17} /></button>
    </section>}
  </div>;
}

function BookingList({role,activeOnly}: {role:string;activeOnly?:boolean}) {
  const data = useData<Booking[]>("/bookings",15000);
  const action = useAction();
  const next: Record<string,string> = {ASSIGNED:"Confirm assignment",CONFIRMED:"Mark en route",DRIVER_EN_ROUTE:"Mark arrived"};
  const rows = data.data?.filter(item=>!activeOnly || ["ASSIGNED","CONFIRMED","DRIVER_EN_ROUTE","DRIVER_ARRIVED","IN_PROGRESS"].includes(item.status));
  return <div className="card"><h3>{role === "driver" ? "Your assignments" : "Booking requests"}</h3><State pending={data.isPending} error={data.error} /><ErrorMessage error={action.error} />
    {rows?.length === 0 && <p>{activeOnly ? "No active assignment." : "No bookings yet."}</p>}
    {rows?.map(item=><div className="record" key={item.id}><div>{role === "driver" ? <Link className="text-link" href={"/driver/trips/"+item.id}>{item.pickup}</Link> : <Link className="text-link" href={"/"+role+"/bookings/"+item.id}>{item.pickup}</Link>}<p>{date(item.starts_at)} · {money(item.fare_paise)}</p></div><Badge value={item.status} />
    {role === "driver" && next[item.status] && <button className="button compact secondary" disabled={action.busy} onClick={()=>void action.run(()=>send("/trips/"+item.id+"/advance",{expected_status:item.status}))}>{next[item.status]}</button>}</div>)}
  </div>;
}

function BookingDetail({id,role,canRelease,canDispute}: {id:string;role:string;canRelease?:boolean;canDispute?:boolean}) {
  const router = useRouter();
  const data = useData<Booking>("/bookings/"+id,10000);
  useBookingEvents(id, role !== "admin" && data.isSuccess);
  const action = useAction();
  const item = data.data;
  return <div className="card"><State pending={data.isPending} error={data.error} />{item && <>
    <div className="record"><h3>{item.pickup}</h3><Badge value={item.status} /></div>
    <div className="record"><span>Booking reference</span><span className="break-all">{item.id}</span></div>
    <div className="record"><span>Pickup time (IST)</span><span>{date(item.starts_at)}</span></div>
    {item.destination && <div className="record"><span>Destination</span><span>{item.destination}</span></div>}
    <div className="record"><span>Estimated fare</span><strong>{money(item.fare_paise)}</strong></div>
    <div className="record"><span>Driver</span><span className="flex items-center gap-2">{role==="customer" && item.driver_has_photo && <Image unoptimized className="rounded-full" src={"/api/v1/bookings/"+item.id+"/driver-photo"} width={40} height={40} alt="Assigned driver" />}{item.driver_name ?? (item.driver_id ? "Assigned" : "Awaiting assignment")}</span></div>
    <ErrorMessage error={action.error} />
    {role === "customer" && ["SEARCHING","ASSIGNED","CONFIRMED","DRIVER_EN_ROUTE"].includes(item.status) && <button className="button secondary" disabled={action.busy} onClick={()=>void action.run(async()=>{
      const fee=await api<{amount_paise:number}>("/bookings/"+id+"/cancellation");
      const question=fee.amount_paise ? "Cancel and accept the "+money(fee.amount_paise)+" late-cancellation fee?" : "Cancel this booking?";
      if(window.confirm(question)) await send("/bookings/"+id+"/cancel?accepted_fee_paise="+fee.amount_paise);
    })}>Cancel booking</button>}
    {(role === "driver" || canRelease) && ["ASSIGNED","CONFIRMED","DRIVER_EN_ROUTE"].includes(item.status) && <button className="button secondary" disabled={action.busy} onClick={()=>{if(window.confirm("Release the current driver and reopen the request if time remains?")) void action.run(async()=>{await send("/trips/"+item.id+"/release");if(role==="driver") router.push("/driver/active-trip");});}}>Release assignment</button>}
    {canDispute && ["COMPLETED","CANCELLED","EXPIRED"].includes(item.status) && <Fields onSubmit={fields=>void action.run(()=>send("/admin/bookings/"+item.id+"/dispute",Object.fromEntries(fields)))}>
      <label>Reason for dispute<textarea name="reason" required minLength={8} maxLength={2000} /></label>
      <button className="button compact secondary" disabled={action.busy}>Open booking dispute</button>
    </Fields>}
    {canDispute && item.status==="DISPUTED" && <button className="button compact secondary" disabled={action.busy} onClick={()=>{
      if(window.confirm("Resolve the booking dispute and restore its previous status?")) void action.run(()=>send("/admin/bookings/"+item.id+"/resolve"));
    }}>Resolve dispute</button>}
    {role === "driver" && <a className="text-link mt-4" href={"https://www.google.com/maps/dir/?api=1&destination="+encodeURIComponent(item.pickup_latitude===null||item.pickup_longitude===null ? item.pickup : (item.pickup_latitude/1000000)+","+(item.pickup_longitude/1000000))} target="_blank" rel="noreferrer">Pickup directions</a>}
  </>}{item && role !== "admin" && <BookingMap booking={item} />}{item && role !== "admin" && ["DRIVER_EN_ROUTE","DRIVER_ARRIVED","IN_PROGRESS"].includes(item.status) && <LocationPanel booking={item} driver={role === "driver"} />}{item && role === "customer" && <Payments booking={item} />}{item && role!=="admin" && item.status==="DRIVER_ARRIVED" && <PickupVerificationPanel booking={item} customer={role==="customer"} />}{item && <BookingTimeline id={item.id} />}{item && <Handovers booking={item} role={role} />}{item && role !== "admin" && <BookingSafety booking={item} customer={role === "customer"} />}</div>;
}

function BookingTimeline({id}: {id:string}) {
  const data=useData<{id:string;status:string;created_at:string}[]>("/bookings/"+id+"/events",10000);
  return <details className="mt-6"><summary className="font-semibold">Booking activity</summary>
    <State pending={data.isPending} error={data.error} />
    {data.data?.map(event=><div className="record" key={event.id}><Badge value={event.status} /><time dateTime={event.created_at}>{date(event.created_at)}</time></div>)}
  </details>;
}

function Availability() {
  const data = useData<Driver>("/drivers/me");
  const action = useAction();
  const item = data.data;
  return <div className="card"><h3>Service preferences</h3><State pending={data.isPending} error={data.error} />{item && <>
    <p>{item.approved ? "Approved driver" : "Awaiting approval. You can save your preferences now."}</p>
    <Fields onSubmit={fields=>void action.run(()=>send("/availability",{area:"Bengaluru",transmission:fields.get("transmission"),online:fields.has("online"),categories:fields.getAll("categories"),schedule_only:fields.has("schedule")},"PUT"))}>
      <label>Service area<input value="Bengaluru" readOnly /></label>
      <label>Transmission experience<select name="transmission" defaultValue={item.transmission || "manual"}><option value="manual">Manual</option><option value="automatic">Automatic</option><option value="both">Both</option></select></label>
      <fieldset><legend>Vehicle experience</legend>{categories.map(([value,label])=><label key={value} className="row"><input type="checkbox" name="categories" value={value} defaultChecked={!item.categories||item.categories.split(",").includes(value)} /> {label}</label>)}</fieldset>
      <label className="row"><input type="checkbox" name="schedule" defaultChecked={item.schedule_only} /> Only accept requests during my scheduled windows</label>
      <label className="row"><input type="checkbox" name="online" defaultChecked={item.online} disabled={!item.approved} /> Available for requests</label>
      <ErrorMessage error={action.error} /><button className="button" disabled={action.busy}>Save preferences</button>
    </Fields>
    {item.online && <><p>Share your current position for near-term matching. It stops influencing offers after 20 minutes.</p>
      <div className="flex flex-wrap gap-2 mt-3">
        <button className="button compact secondary" disabled={action.busy} onClick={()=>void action.run(async()=>send("/availability/dispatch-point",await currentPosition(),"PUT"))}>{item.dispatch_at?"Refresh dispatch location":"Share dispatch location"}</button>
        {item.dispatch_at && <button className="button compact secondary" disabled={action.busy} onClick={()=>void action.run(()=>send("/availability/dispatch-point",undefined,"DELETE"))}>Clear dispatch location</button>}
      </div>
      {item.dispatch_at && <p className="notice">Last shared {date(item.dispatch_at)}</p>}
    </>}
    <AvailabilityWindows />
  </>}</div>;
}

function AvailabilityWindows() {
  const windows = useData<{id:string;starts_at:string;ends_at:string}[]>("/availability/windows");
  const action = useAction();
  return <section className="mt-6"><h3>Scheduled availability</h3><State pending={windows.isPending} error={windows.error} />
    {windows.data?.length===0 && <p>No upcoming availability windows.</p>}
    {windows.data?.map(row=><div key={row.id} className="record"><span>{date(row.starts_at)} to {date(row.ends_at)}</span>
      <button className="button compact secondary" disabled={action.busy} onClick={()=>void action.run(()=>send("/availability/windows/"+row.id,undefined,"DELETE"))}>Remove window</button>
    </div>)}
    <Fields onSubmit={(fields,form)=>void action.run(async()=>{await send("/availability/windows",{starts_at:String(fields.get("start"))+":00+05:30",ends_at:String(fields.get("end"))+":00+05:30"});form.reset();})}>
      <label>Available from (IST)<input type="datetime-local" name="start" required /></label>
      <label>Available until (IST)<input type="datetime-local" name="end" required /></label>
      <button className="button compact" disabled={action.busy}>Add availability window</button>
    </Fields><ErrorMessage error={action.error} />
  </section>;
}

function OfferDeadline({value}: {value:string}) {
  const [now,setNow]=useState<number|null>(null);
  useEffect(()=>{
    const timer=setInterval(()=>setNow(Date.now()),1000);
    return ()=>clearInterval(timer);
  },[]);
  const seconds=now===null?null:Math.max(0,Math.ceil((Date.parse(value)-now)/1000));
  if(seconds===0) return <p>Offer expired</p>;
  if(seconds===null || seconds>=3600) return <p>Expires {date(value)}</p>;
  return <p>Expires in {Math.floor(seconds/60)}:{String(seconds%60).padStart(2,"0")}</p>;
}

function Offers() {
  const offers = useData<Offer[]>("/booking-offers",10000);
  const action = useAction();
  const router = useRouter();
  return <div className="card"><h3>Available requests</h3><State pending={offers.isPending} error={offers.error} /><ErrorMessage error={action.error} />
    {offers.data?.length === 0 && <p>No matching requests. Approved drivers must be online to receive requests.</p>}
    {offers.data?.map(item=><div className="record" key={item.id}><div><strong>{item.area}</strong><p>{date(item.starts_at)} · {item.hours} hours · {item.category} · {item.transmission}</p>{item.distance_km!==null && <p>Pickup approximately {item.distance_km} km away</p>}<OfferDeadline value={item.expires_at} /></div><button className="button compact" disabled={action.busy} onClick={()=>void action.run(async()=>{await send("/booking-offers/"+item.id+"/accept");router.push("/driver/trips");})}>Accept request</button><button className="button compact secondary" disabled={action.busy} onClick={()=>void action.run(()=>send("/booking-offers/"+item.id+"/decline"))}>Decline</button></div>)}
  </div>;
}

function Support({role}: {role:string}) {
  const data = useData<Ticket[]>("/support");
  const action = useAction();
  return <><div className="card"><h3>{role === "admin" ? "Support inbox" : "Your support tickets"}</h3><ErrorMessage error={action.error} /><State pending={data.isPending} error={data.error} />
    {data.data?.length === 0 && <p>No support tickets yet.</p>}
    {data.data?.map(ticket=><div className="record" key={ticket.id}><p className="break-all">{ticket.message}</p><Badge value={ticket.status} /><TicketConversation ticket={ticket} />{role === "admin" && ticket.status === "OPEN" && <button className="button compact secondary" disabled={action.busy} onClick={()=>void action.run(()=>send("/admin/support/"+ticket.id+"/close"))}>Close ticket</button>}</div>)}
  </div>{role !== "admin" && <div className="card"><h3>Open a ticket</h3><Fields onSubmit={(fields,form)=>void action.run(async()=>{await send("/support",Object.fromEntries(fields));form.reset();})}>
    <label>How can we help?<textarea name="message" rows={4} required minLength={10} maxLength={2000} /></label>
    <ErrorMessage error={action.error} /><button className="button" disabled={action.busy}>Submit ticket</button>
  </Fields></div>}</>;
}

function TicketConversation({ticket}: {ticket:Ticket}) {
  const [open,setOpen]=useState(false);
  const endpoint="/support/"+ticket.id+"/replies";
  const data=useData<{id:string;message:string;name:string;created_at:string}[]>(endpoint,15000,open);
  const action=useAction();
  return <div className="w-full"><button className="text-link" onClick={()=>setOpen(!open)} aria-expanded={open}>{open?"Hide conversation":"Open conversation"}</button>
    {open && <div className="mt-3"><State pending={data.isPending} error={data.error} />
      {data.data?.length===0 && <p>No replies yet.</p>}
      {data.data?.map(reply=><div className="record" key={reply.id}><div><strong>{reply.name}</strong><p>{reply.message}</p></div><small>{date(reply.created_at)}</small></div>)}
      {ticket.status==="OPEN" && <Fields onSubmit={(fields,form)=>void action.run(async()=>{await send(endpoint,Object.fromEntries(fields));form.reset();})}>
        <label>Reply<textarea name="message" required minLength={2} maxLength={2000} /></label><button className="button compact" disabled={action.busy}>Send reply</button>
      </Fields>}<ErrorMessage error={action.error} />
    </div>}
  </div>;
}

function AdminOverview({scope}: {scope:Profile["staff_scope"]}) {
  const showOperations = !scope || scope === "operations";
  const showFinance = !scope || scope === "finance";
  const data = useData<Record<string,number>>("/admin/metrics",15000,showOperations);
  const finance = useData<Record<string,number>>("/admin/financials",15000,showFinance);
  if (scope === "support") return <div className="card"><h3>Support workspace</h3><p>Review new reports and manage open support cases.</p><Link href="/admin/support" className="text-link">Open support inbox</Link></div>;
  return <>{showOperations && <State pending={data.isPending} error={data.error} />}<div className="cards">{Object.entries(data.data ?? {}).map(([label,value])=><div className="card" key={label}><p>{label}</p><h3>{value}</h3></div>)}</div>
    {showFinance && <State pending={finance.isPending} error={finance.error} />}<div className="cards">{Object.entries(finance.data ?? {}).map(([label,value])=><div className="card" key={label}><p>{label}</p><h3>{money(value)}</h3></div>)}</div></>;
}

const navigationGroups = [
  {title:"Workspace", sections:["dashboard","book","active-trip","onboarding"]},
  {title:"Operations", sections:["customers","drivers","vehicles","addresses","verification","verifications","bookings","live-operations","availability","requests","trips","documents","skill-passport"]},
  {title:"Finance", sections:["pricing","commissions","payments","refunds","payouts","receipts","reports","earnings"]},
  {title:"Account and support", sections:["incidents","reviews","support","notifications","profile","staff","audit-logs","settings"]},
];

export function Portal({user,tab,id,tabs,plan}: {user:Profile;tab:string;id?:string;tabs:string[];plan?:string}) {
  const router = useRouter();
  const query = useQueryClient();
  const action = useAction();
  const nav = (name:string)=>name === "dashboard" ? workspaceHome(user.role) : "/" + user.role + "/" + name;
  let panel:ReactNode;
  switch(tab) {
    case "vehicles": panel=<VehiclePanel />;break;
    case "book": panel=<BookingForm plan={plan} />;break;
    case "bookings": panel=id ? <BookingDetail id={id} role={user.role} canRelease={user.role==="admin" && (!user.staff_scope || user.staff_scope==="operations")} canDispute={user.role==="admin" && user.staff_scope!=="finance"} /> : user.role==="admin" ? <AdvancedPanel role={user.role} tab={tab} /> : <BookingList role={user.role} />;break;
    case "trips": panel=id ? <BookingDetail id={id} role={user.role} /> : <BookingList role={user.role} />;break;
    case "documents":
    case "verification":
    case "verifications": panel=<Documents admin={user.role === "admin"} />;break;
    case "earnings": panel=<Earnings />;break;
    case "payments": panel=user.role === "admin" ? <AdvancedPanel role={user.role} tab={tab} /> : <Payments />;break;
    case "active-trip": panel=<BookingList role="driver" activeOnly />;break;
    case "availability": panel=<Availability />;break;
    case "requests": panel=<Offers />;break;
    case "support": panel=<Support role={user.role} />;break;
    case "settings":
    case "profile": panel=user.role === "admin" ? <AdvancedPanel role={user.role} tab={tab} /> : <ProfileSettings user={user} />;break;
    case "dashboard": panel=user.role === "owner" ? <OwnerOverview /> : user.role === "admin" ? <AdminOverview scope={user.staff_scope} /> : <><div className="card"><h3>Welcome, {user.name}</h3><p>{user.role === "customer" ? "Manage your vehicles and upcoming driver requests." : "Manage availability and review driver requests."}</p><Link className="button compact mt-4" href={nav(user.role === "customer" ? "book" : "availability")}>{user.role === "customer" ? "Book a driver" : "Set availability"} <ArrowRight size={17} /></Link></div><BookingList role={user.role} /></>;break;
    default: panel=<AdvancedPanel role={user.role} tab={tab} />;
  }
  return <main className="portal"><div className="wrap portal-layout"><nav className="portal-nav" aria-label="Workspace">
    <div className="portal-nav-heading"><p className="eyebrow">{user.role} workspace</p><strong>{user.name}</strong></div>
    <div className="portal-nav-groups">{navigationGroups.map(group=>{
      const visible=group.sections.filter(name=>tabs.includes(name));
      return visible.length>0 && <div className="portal-nav-group" key={group.title}><p>{group.title}</p>{visible.map(name=><Link key={name} href={nav(name)} aria-current={tab === name ? "page":undefined}>{labels[name]}</Link>)}</div>;
    })}</div>
    <label className="portal-mobile-navigation">Workspace section<select value={tab} onChange={event=>router.push(nav(event.target.value))}>{navigationGroups.map(group=>{
      const visible=group.sections.filter(name=>tabs.includes(name));
      return visible.length>0 && <optgroup key={group.title} label={group.title}>{visible.map(name=><option key={name} value={name}>{labels[name]}</option>)}</optgroup>;
    })}</select></label>
    <button className="button compact secondary" disabled={action.busy} onClick={()=>void action.run(async()=>{await send("/auth/logout");query.clear();router.replace("/login");router.refresh();})}><LogOut size={16} /> Sign out</button><ErrorMessage error={action.error} />
  </nav><div className="portal-main"><h1 className="page-title">{id ? "Booking details" : labels[tab]}</h1>{panel}</div></div></main>;
}

type Licence = {id:string; licence_number:string; licence_expiry:string; status:string; driver_name?:string};

function Documents({admin}: {admin:boolean}) {
  const path = admin ? "/admin/verifications" : "/drivers/documents";
  const documents = useData<Licence[]>(path);
  const action = useAction();
  return <div className="card"><h3>{admin ? "Submitted licences" : "Your driving licence"}</h3>
    <State pending={documents.isPending} error={documents.error} />
    {documents.data?.length === 0 && <p>No licences submitted.</p>}
    {documents.data?.map(item=><div className="record" key={item.id}>
      <div><strong>{item.driver_name ?? item.licence_number}</strong>{admin && <p>{item.licence_number} · Valid until {date(item.licence_expiry)}</p>}</div><Badge value={item.status} />
      {admin && <a className="text-link" href={"/api/v1/admin/verifications/"+item.id+"/download"}>Download PDF</a>}
      {admin && item.status === "PENDING" && <div className="flex gap-2">
        <Fields onSubmit={fields=>{
          const verified_categories=fields.getAll("verified_categories");
          if(verified_categories.length) void action.run(()=>send(path+"/"+item.id,{decision:"APPROVED",verified_categories}));
        }}>
          <label>Categories supported by the reviewed licence<select name="verified_categories" multiple required size={4}>{categories.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
          <button className="button compact" disabled={action.busy}>Approve</button>
        </Fields>
        <button className="button compact secondary" disabled={action.busy} onClick={()=>void action.run(()=>send(path+"/"+item.id,{decision:"REJECTED"}))}>Reject</button>
      </div>}
    </div>)}
    <ErrorMessage error={action.error} />
    {!admin && <Fields onSubmit={(fields,form)=>void action.run(async()=>{await api(path,{method:"POST",body:fields});form.reset();})}>
      <label>Licence number<input name="licence_number" minLength={5} maxLength={30} required /></label>
      <label>Expiry date<input name="expiry" type="date" required /></label>
      <label>Licence PDF (up to 2 MB)<input name="document" type="file" accept="application/pdf" required /></label>
      <button className="button" disabled={action.busy}>Submit for review</button>
    </Fields>}
  </div>;
}

function PickupVerificationPanel({booking,customer}: {booking:Booking;customer:boolean}) {
  const path="/trips/"+booking.id+"/pickup-verification";
  const data=useData<{verified:boolean}>(path,10000);
  const action=useAction();
  const [code,setCode]=useState<{code:string;expires_at:string}|null>(null);
  return <section className="mt-6"><h3>Verify pickup</h3><State pending={data.isPending} error={data.error} />
    {data.data?.verified ? <p>Pickup code verified.</p> : customer ? <>
      <p>Share the code with your assigned driver in person.</p>
      {code && <p role="status"><strong className="text-xl tracking-widest">{code.code}</strong> · Expires {date(code.expires_at)}</p>}
      <button className="button compact secondary mt-2" disabled={action.busy} onClick={()=>void action.run(async()=>setCode(await send(path)))}>{code?"Generate new pickup code":"Generate pickup code"}</button>
    </> : <Fields onSubmit={fields=>void action.run(()=>send(path+"/check",Object.fromEntries(fields)))}>
      <label>Customer&apos;s six-digit pickup code<input required name="code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} /></label>
      <button className="button compact" disabled={action.busy}>Verify pickup code</button>
    </Fields>}<ErrorMessage error={action.error} />
  </section>;
}

type Handover = {id:string; stage:string; odometer:number; fuel_percent:number; condition:string; acknowledged:boolean};

function Handovers({booking,role}: {booking:Booking;role:string}) {
  const path = "/handovers/"+booking.id;
  const data = useData<Handover[]>(path,10000);
  const photos = useData<{id:string;stage:string}[]>(path+"/photos",10000);
  const action = useAction();
  const stage = booking.status === "DRIVER_ARRIVED" ? "before" : booking.status === "IN_PROGRESS" ? "after" : undefined;
  const ready = data.data?.find(item=>item.stage === stage);
  return <section className="mt-6" aria-label="Vehicle handover">
    <h3>Vehicle handover</h3><State pending={data.isPending} error={data.error} />
    {data.data?.length === 0 && <p>No handover recorded yet.</p>}
    {data.data?.map(item=><div className="record" key={item.id}><div><strong>{item.stage === "before" ? "Before trip" : "After trip"}</strong><p>{item.odometer} km · {item.fuel_percent}% fuel</p><p>{item.condition}</p></div>
      {role === "customer" && !item.acknowledged ? <button className="button compact" disabled={action.busy} onClick={()=>void action.run(()=>send(path+"/"+item.stage+"/acknowledge"))}>Acknowledge</button> : <Badge value={item.acknowledged ? "acknowledged" : "awaiting acknowledgement"} />}
    </div>)}
    {!!photos.data?.length && <div className="handover-photos">{photos.data.map(photo=><a key={photo.id} href={"/api/v1"+path+"/photos/"+photo.id} target="_blank" rel="noreferrer"><Image unoptimized width={160} height={106} src={"/api/v1"+path+"/photos/"+photo.id} alt={photo.stage==="before"?"Vehicle before trip":"Vehicle after trip"} /></a>)}</div>}
    {role === "driver" && stage && ready && !ready.acknowledged && (photos.data?.filter(photo=>photo.stage===stage).length??0)<4 &&
      <Fields onSubmit={(fields,form)=>void action.run(async()=>{await api(path+"/"+stage+"/photos",{method:"POST",body:fields});form.reset();})}>
        <label>Optional vehicle photo (max 3 MB)<input type="file" name="photo" accept="image/jpeg,image/png,image/webp" required /></label>
        <button className="button compact secondary" disabled={action.busy}>Upload photo</button>
      </Fields>}
    {role === "driver" && stage && data.data && !ready && <Fields key={stage} onSubmit={fields=>void action.run(()=>send(path,{stage,condition:fields.get("condition"),odometer:Number(fields.get("odometer")),fuel_percent:Number(fields.get("fuel_percent"))}))}>
      <label>Odometer (km)<input name="odometer" type="number" min={0} max={2000000} required /></label>
      <label>Fuel (%)<input name="fuel_percent" type="number" min={0} max={100} required /></label>
      <label>Vehicle condition and damage<textarea name="condition" minLength={3} maxLength={2000} required /></label>
      <button className="button" disabled={action.busy}>Record handover</button>
    </Fields>}
    {role === "driver" && stage && ready?.acknowledged && <button className="button" disabled={action.busy} onClick={()=>void action.run(()=>send("/trips/"+booking.id+"/advance",{expected_status:booking.status}))}>{stage === "before" ? "Start trip" : "Complete trip"}</button>}
    <ErrorMessage error={action.error} />
  </section>;
}

function Earnings() {
  const data = useData<{booking_id:string; gross_paise:number; commission_paise:number; net_paise:number; status:string}[]>("/drivers/earnings");
  const payouts=useData<{id:string;booking_id:string;amount_paise:number;status:string;reference:string|null}[]>("/drivers/payout-history");
  return <><div className="card"><h3>Trip earnings</h3><p>Amounts accrue on completion and remain unsettled until paid.</p><State pending={data.isPending} error={data.error} />
    {data.data?.length === 0 && <p>No completed trip earnings.</p>}
    {data.data?.map(item=><div className="record" key={item.booking_id}><div><Link className="text-link" href={"/driver/trips/"+item.booking_id}>Trip details</Link><p>Gross {money(item.gross_paise)} · Commission {money(item.commission_paise)}</p></div><strong>{money(item.net_paise)}</strong><Badge value={item.status} /></div>)}
  </div><div className="card"><h3>Payout history</h3><State pending={payouts.isPending} error={payouts.error} />
    {payouts.data?.length===0 && <p>No payout records yet.</p>}
    {payouts.data?.map(item=><div className="record" key={item.id}><div><Link className="text-link" href={"/driver/trips/"+item.booking_id}>View trip</Link>{item.reference && <p>{item.reference}</p>}</div><strong>{money(item.amount_paise)}</strong><Badge value={item.status} /></div>)}
  </div></>;
}

type ChargeKind = "BASE"|"OVERAGE"|"CANCELLATION";
type Charge = {id:string;kind:ChargeKind;amount_paise:number;description:string};
const paymentTitles:Record<ChargeKind,string>={BASE:"Booking fare",OVERAGE:"Post-trip overage",CANCELLATION:"Late cancellation fee"};
type Payment = {id:string; booking_id:string; kind:ChargeKind; amount_paise:number; status:string; provider_order_id:string|null};
type RazorpayResult = {razorpay_order_id:string; razorpay_payment_id:string; razorpay_signature:string};
type RazorpayOptions = {key:string; amount:number; currency:"INR"; name:string; order_id:string; handler:(result:RazorpayResult)=>void};

function loadCheckout(): Promise<new (options:RazorpayOptions)=>{open:()=>void}> {
  const checkout = window as Window & {Razorpay?:new (options:RazorpayOptions)=>{open:()=>void}};
  return new Promise((resolve,reject)=>{
    if (checkout.Razorpay) {resolve(checkout.Razorpay);return;}
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => checkout.Razorpay ? resolve(checkout.Razorpay) : reject(new Error("Checkout could not start."));
    script.onerror = () => {script.remove();reject(new Error("Checkout could not load."));};
    document.head.appendChild(script);
  });
}

function Payments({booking}: {booking?:Booking}) {
  const data = useData<{configured:boolean;test_mode:boolean;mode:"demo"|"razorpay"; payments:Payment[]; demo_payments:Payment[]}>("/payments"+(booking?"?booking_id="+booking.id:""),10000);
  const action = useAction();
  const rows = data.data?.payments;
  const demo = data.data?.demo_payments;
  const charges=useData<Charge[]>("/payments/"+booking?.id+"/charges",10000,Boolean(booking));
  const payable:Charge[]=[...(booking?.status==="DRIVER_ARRIVED"?[{id:"base",kind:"BASE" as const,amount_paise:booking.fare_paise,description:"Booking fare"}]:[]),...(charges.data??[])];
  const demoMode = data.data?.mode === "demo";
  async function pay(item:Booking,kind:ChargeKind) {
    const Checkout = await loadCheckout();
    const order = await send<Payment & {key_id:string}>("/payments/"+item.id+"/order?kind="+kind);
    if (!order.provider_order_id) throw new Error("The payment provider did not return an order.");
    new Checkout({
      key:order.key_id,amount:order.amount_paise,currency:"INR",name:"Drivewell",order_id:order.provider_order_id,
      handler:result=>void action.run(()=>send("/payments/"+item.id+"/verify",{
        order_id:result.razorpay_order_id,payment_id:result.razorpay_payment_id,signature:result.razorpay_signature,
      })),
    }).open();
  }
  return <section className={booking ? "mt-6" : "card"} aria-label="Payments">
    <h3>{booking ? "Booking payment" : "Payment history"}</h3>
    <State pending={data.isPending} error={data.error} /><ErrorMessage error={action.error} />
    {data.data && !demoMode && !data.data.configured && <p>Online checkout is unavailable in this environment.</p>}
    {rows?.length === 0 && !demo?.length && !booking && <p>No payments recorded.</p>}
    {demoMode && <p className="notice">Demo checkout · No money is charged and no real payment receipt is issued.</p>}
    {data.data?.test_mode && <p className="notice">Razorpay test mode · Test transactions only.</p>}
    {demo?.map(item=><div className="record" key={item.id}><Link className="text-link" href={"/customer/bookings/"+item.booking_id}>{paymentTitles[item.kind]}</Link><strong>{money(item.amount_paise)}</strong><Badge value="SIMULATED" /></div>)}
    {rows?.map(item=><div className="record" key={item.id}><Link className="text-link" href={"/customer/bookings/"+item.booking_id}>{paymentTitles[item.kind]}</Link><strong>{money(item.amount_paise)}</strong><Badge value={item.status === "CREATING" ? "requires reconciliation" : item.status} /></div>)}
    {booking && charges.error && <ErrorMessage error={charges.error.message} />}
    {booking && payable.map(charge=>{
      const existing=rows?.find(item=>item.kind===charge.kind);
      const simulated=demo?.some(item=>item.kind===charge.kind);
      if(simulated || (existing && existing.status!=="CREATED")) return null;
      return <div className="record checkout-record" key={charge.id}><span>{charge.description}</span><strong>{money(charge.amount_paise)}</strong>
        {demoMode && !existing && <button className="button compact" disabled={action.busy} onClick={()=>void action.run(()=>send("/payments/"+booking.id+"/demo?kind="+charge.kind))}>Simulate payment of {money(charge.amount_paise)}</button>}
        {data.data?.configured && <button className="button compact" disabled={action.busy} onClick={()=>void action.run(()=>pay(booking,charge.kind))}>Pay {money(charge.amount_paise)}</button>}
      </div>;
    })}
  </section>;
}

function useBookingEvents(id: string, enabled: boolean) {
  const query = useQueryClient();
  useEffect(()=>{
    if (!enabled) return;
    let socket:WebSocket|undefined;
    let timer:ReturnType<typeof setTimeout>|undefined;
    let stopped = false;
    let delay = 3000;
    function connect() {
      const url = new URL("/api/v1/realtime/bookings/"+id, window.location.origin);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(url);
      socket.onopen = ()=>{delay=3000;};
      socket.onmessage = ()=>{
        for (const path of ["/bookings/","/locations/","/handovers/"]) {
          void query.invalidateQueries({queryKey:[path+id]});
        }
      };
      socket.onclose = event=>{
        if (stopped || event.code === 1008) return;
        timer=setTimeout(connect,delay);
        delay=Math.min(delay * 2, 30000);
      };
    }
    connect();
    return ()=>{stopped=true;clearTimeout(timer);socket?.close();};
  },[id,enabled,query]);
}

type DriverPosition = {latitude:number; longitude:number; accuracy_m:number; recorded_at:string; stale:boolean};

function BookingMap({booking}: {booking:Booking}) {
  const active=["DRIVER_EN_ROUTE","DRIVER_ARRIVED","IN_PROGRESS"].includes(booking.status);
  const location=useData<DriverPosition|null>("/locations/"+booking.id,10000,active);
  const routing=useAction();
  const [route,setRoute]=useState<Route|null>(null);
  const pickup:Point|null=booking.pickup_latitude!==null && booking.pickup_longitude!==null
    ? {latitude:booking.pickup_latitude/1000000,longitude:booking.pickup_longitude/1000000} : null;
  const live=active?location.data:null;
  const driver=live?{latitude:live.latitude,longitude:live.longitude}:null;
  const origin=pickup ? pickup.latitude+","+pickup.longitude : booking.pickup;
  const href="https://www.google.com/maps/dir/?api=1&destination="+encodeURIComponent(booking.destination||origin)+(booking.destination?"&origin="+encodeURIComponent(origin):"");
  return <section className="mt-6" aria-label="Booking map">
    <h3>Booking map</h3>
    <TripMap pickup={pickup} driver={driver} route={route} />
    {live && <p className="notice">{live.stale?"Last known driver location":"Driver location shared"} · {date(live.recorded_at)}</p>}
    {!pickup&&!driver&&!route && <p className="notice">A pickup pin or shared driver location is needed to show markers.</p>}
    <div className="flex flex-wrap gap-2 mt-3">
      {booking.destination && <button className="button compact secondary" disabled={routing.busy} onClick={()=>void routing.run(async()=>setRoute(await send("/maps/bookings/"+booking.id+"/route",{mode:"planned"})))}>Show planned route</button>}
      {live && !live.stale && <button className="button compact secondary" disabled={routing.busy} onClick={()=>void routing.run(async()=>setRoute(await send("/maps/bookings/"+booking.id+"/route",{mode:"driver"})))}>Estimate driving time from driver</button>}
      <a className="text-link" href={href} target="_blank" rel="noreferrer">Open directions in Google Maps</a>
    </div>
    {route && <RouteDetails route={route} />}
    <ErrorMessage error={routing.error} />
  </section>;
}

function LocationPanel({booking,driver}: {booking:Booking;driver:boolean}) {
  const path = "/locations/"+booking.id;
  const data = useData<DriverPosition|null>(path,15000);
  const action = useAction();
  const point = data.data;
  const [tracking,setTracking] = useState(false);
  const [trackingError,setTrackingError] = useState("");
  const query = useQueryClient();
  const lastUpdate = useRef(0);
  useEffect(()=>{
    if (!tracking || !navigator.geolocation) return;
    let stopped = false;
    const watch = navigator.geolocation.watchPosition(position=>{
      const now = Date.now();
      if (stopped || now-lastUpdate.current<15000) return;
      lastUpdate.current = now;
      const {latitude,longitude,accuracy} = position.coords;
      void send(path,{latitude,longitude,accuracy_m:accuracy}).then(()=>{
        if (!stopped) {
          setTrackingError("");
          void query.invalidateQueries({queryKey:[path]});
        }
      }).catch(error=>{
        if (!stopped) setTrackingError(error instanceof Error?error.message:"Location could not be shared.");
      });
    },error=>{if(!stopped)setTrackingError(error.message);},{enableHighAccuracy:true,timeout:12000});
    return ()=>{stopped=true;navigator.geolocation.clearWatch(watch);};
  },[path,query,tracking]);
  return <section className="mt-6" aria-label="Driver location">
    <h3>Driver location</h3><State pending={data.isPending} error={data.error} /><ErrorMessage error={action.error} />
    {point ? <div className="record"><div><strong>{point.stale ? "Last known location · stale" : "Recently shared location"}</strong>
      <p>{date(point.recorded_at)} · approximately {point.accuracy_m} m accuracy</p></div>
      <a className="text-link" href={"https://www.google.com/maps/search/?api=1&query="+encodeURIComponent(point.latitude+","+point.longitude)} target="_blank" rel="noreferrer">Open map</a>
    </div> : data.isSuccess && <p>No location shared yet.</p>}
    {driver && <><p className="notice">Share your location with the customer for this booking. Live sharing needs this page open and may pause in the background.</p>
      <ErrorMessage error={trackingError} />
      {tracking ? <button className="button compact secondary" onClick={()=>{setTracking(false);setTrackingError("");}}>Stop live sharing</button>
        : <button className="button compact secondary" onClick={()=>{if(navigator.geolocation){setTracking(true);setTrackingError("");}else setTrackingError("Location is unavailable in this browser.");}}>Start live sharing</button>}
      <button className="button compact secondary" disabled={action.busy||tracking} onClick={()=>void action.run(async()=>{
        if (!navigator.geolocation) throw new Error("Location is unavailable in this browser.");
        const coords = await new Promise<GeolocationCoordinates>((resolve,reject)=>
          navigator.geolocation.getCurrentPosition(result=>resolve(result.coords),error=>reject(new Error(error.message)),{enableHighAccuracy:true,timeout:12000})
        );
        await send(path,{latitude:coords.latitude,longitude:coords.longitude,accuracy_m:coords.accuracy});
      })}>Share current location</button>
    </>}
  </section>;
}
