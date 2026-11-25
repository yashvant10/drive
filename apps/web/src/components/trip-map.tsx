"use client";

import { useEffect, useRef, useState } from "react";
import type { LayerGroup, Map as LeafletMap } from "leaflet";
import "leaflet/dist/leaflet.css";

export type Point = {latitude:number;longitude:number};
export type Route = {line:[number,number][]; distance_m:number; duration_s:number;provider:string};
type Props = {pickup?:Point|null; driver?:Point|null; route?:Route|null; onPick?:(point:Point)=>void};

const bengaluru:[number,number] = [12.9716,77.5946];
const tile = process.env.NEXT_PUBLIC_MAP_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const attribution = process.env.NEXT_PUBLIC_MAP_TILE_ATTRIBUTION || '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

export function TripMap({pickup,driver,route,onPick}: Props) {
  const element = useRef<HTMLDivElement>(null);
  const map = useRef<LeafletMap|null>(null);
  const layer = useRef<LayerGroup|null>(null);
  const [ready,setReady] = useState(false);
  const [tileError,setTileError] = useState(false);
  const [failed,setFailed] = useState(false);
  useEffect(()=>{
    let disposed = false;
    let observer:ResizeObserver|undefined;
    void import("leaflet").then(L=>{
      if (disposed || !element.current) return;
      const instance = L.map(element.current,{scrollWheelZoom:false, keyboard:true, zoomControl:true}).setView(bengaluru,12);
      map.current=instance;
      layer.current=L.layerGroup().addTo(instance);
      L.tileLayer(tile,{attribution,maxZoom:19,referrerPolicy:"strict-origin-when-cross-origin"}).on("tileerror",()=>setTileError(true)).addTo(instance);
      observer=new ResizeObserver(()=>instance.invalidateSize({pan:false}));
      observer.observe(element.current);
      setReady(true);
    }).catch(()=>{if(!disposed)setFailed(true);});
    return ()=>{disposed=true;observer?.disconnect();map.current?.remove();map.current=null;layer.current=null;};
  },[]);
  useEffect(()=>{
    const instance=map.current;
    if(!ready || !instance || !onPick) return;
    const handle=(event:import("leaflet").LeafletMouseEvent)=>onPick({latitude:event.latlng.lat,longitude:event.latlng.lng});
    instance.on("click",handle);
    return ()=>{instance.off("click",handle);};
  },[ready,onPick]);
  useEffect(()=>{
    if(!ready) return;
    let disposed=false;
    void import("leaflet").then(L=>{
      const group=layer.current;
      const instance=map.current;
      if(disposed||!group||!instance) return;
      group.clearLayers();
      const bounds=L.latLngBounds([]);
      function point(value:Point|null|undefined,color:string,caption:string,target:LayerGroup){
        if(!value) return;
        const loc:[number,number]=[value.latitude,value.longitude];
        L.circleMarker(loc,{color,fillColor:color,fillOpacity:0.9,radius:7,weight:2}).bindTooltip(caption).addTo(target);
        bounds.extend(loc);
      }
      if(route?.line.length){
        L.polyline(route.line,{color:"#1d4ed8",weight:5}).addTo(group);
        for(const loc of route.line) bounds.extend(loc);
      }
      point(pickup,"#1d4ed8","Pickup",group);
      point(driver,"#047857","Driver location",group);
      if(bounds.isValid()&&!onPick) instance.fitBounds(bounds,{padding:[24,24],maxZoom:15});
    });
    return ()=>{disposed=true;};
  },[ready,pickup,driver,route,onPick]);
  if(failed) return <p role="status">The interactive map could not load. Use the directions link or enter an address.</p>;
  return <div className="trip-map-wrap">
    <div ref={element} className="trip-map" role="region" aria-label={onPick?"Interactive pickup map":"Trip map"} />
    {onPick && <p className="notice">Tap the map to set a pickup pin. You can also enter the address or use your current location.</p>}
    {onPick && pickup && <p>Pickup pin {pickup.latitude.toFixed(5)}, {pickup.longitude.toFixed(5)}</p>}
    {tileError && <p role="status" className="notice">Some map tiles are unavailable. Coordinates and directions are still available.</p>}
  </div>;
}

export function RouteDetails({route}: {route:Route}) {
  return <p className="notice">{(route.distance_m/1000).toFixed(1)} km · about {Math.max(1,Math.ceil(route.duration_s/60))} min driving time. Estimated by {route.provider}.</p>;
}
