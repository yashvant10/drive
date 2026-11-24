"use client";

import { useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { Header, Footer } from "@/components/site";
import { date, send, statusText } from "@/lib/api";

const subscribe = (callback:()=>void)=>{window.addEventListener("hashchange",callback);return ()=>window.removeEventListener("hashchange",callback);};
const tokenFromHash=()=>window.location.hash.slice(1);
type Shared = {status:string;location:{latitude:number;longitude:number;stale:boolean;recorded_at:string}|null};

export default function TripShare() {
  const token=useSyncExternalStore(subscribe,tokenFromHash,()=>"");
  const data=useQuery({queryKey:["guardian-share",token],queryFn:()=>send<Shared>("/family-shares/view",{token}),enabled:token.length===43,refetchInterval:15000,gcTime:0});
  return <><Header /><main className="wrap section subpage"><h1 className="page-title">Shared trip</h1>
    {token.length!==43 && <p>Open the full trip link from the person who shared their trip.</p>}
    {token.length===43 && data.isPending && <p role="status">Loading trip…</p>}
    {data.error && <p className="error" role="alert">{data.error.message}</p>}
    {!data.error && data.data && <div className="card"><p>Trip status <strong>{statusText(data.data.status)}</strong></p>
      {data.data.location ? <><p>{data.data.location.stale ? "Last known location" : "Location shared"} at {date(data.data.location.recorded_at)}</p>
        <a className="text-link" href={"https://www.google.com/maps/search/?api=1&query="+encodeURIComponent(data.data.location.latitude+","+data.data.location.longitude)} target="_blank" rel="noreferrer">Open map</a></> : <p>The driver has not shared a location.</p>}
    </div>}
  </main><Footer /></>;
}
