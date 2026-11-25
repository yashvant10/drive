"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, CalendarCheck2, ReceiptIndianRupee, HandCoins, ReceiptText, ShieldAlert } from "lucide-react";
import { api, money } from "@/lib/api";

type Overview = {
  booking_count:number; completed_trips:number; captured_paise:number;
  refunded_paise:number; paid_out_paise:number; open_safety_cases:number; demo_payment_count:number;
};

const metrics = [
  ["Bookings","booking_count",CalendarCheck2],
  ["Completed trips","completed_trips",Activity],
  ["Captured revenue","captured_paise",ReceiptIndianRupee],
  ["Processed refunds","refunded_paise",ReceiptText],
  ["Processed driver payouts","paid_out_paise",HandCoins],
  ["Open safety cases","open_safety_cases",ShieldAlert],
] as const;

export function OwnerOverview() {
  const data = useQuery({queryKey:["owner-overview"],queryFn:()=>api<Overview>("/owner/overview"),refetchInterval:30000});
  return <section aria-label="All-time business metrics" className="owner-overview">
    <p className="notice">All-time totals from Drivewell records.</p>
    {data.isPending && <p role="status">Loading business metrics…</p>}
    {data.error && <div className="card"><p className="error" role="alert">{data.error.message}</p><button className="button compact secondary mt-3" onClick={()=>void data.refetch()}>Retry metrics</button></div>}
    {data.data && <>
      <div className="owner-metrics">{metrics.map(([name,key,Icon])=><article className="card" key={key}>
        <Icon size={20} aria-hidden="true" /><h2>{name}</h2>
        <strong>{key.endsWith("_paise")?money(data.data![key]):data.data![key].toLocaleString("en-IN")}</strong>
      </article>)}</div>
      <div className="card mt-4"><h2 className="font-semibold">Demo checkout activity</h2><p>{data.data.demo_payment_count.toLocaleString("en-IN")} simulated payment records. These are excluded from the financial totals.</p></div>
    </>}
  </section>;
}
