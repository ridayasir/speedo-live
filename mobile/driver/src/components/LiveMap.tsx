/**
 * OpenStreetMap + Leaflet inside a WebView. No Google Maps key is needed, and the same map
 * style as the web app is used. React Native pushes data in with injectJavaScript; the map
 * sends taps back with postMessage.
 */
import { useEffect, useRef } from "react";
import { StyleSheet, View } from "react-native";
import { WebView } from "react-native-webview";
import type { BusState, Stop } from "../lib/types";
import { effectiveStatus } from "../lib/format";

export interface MapLine { id: number; color: string; path: [number, number][]; dim?: boolean }
export interface MapPoint { lat: number; lng: number; label: string; kind: "origin" | "destination" | "me" }

interface Props {
  buses?: BusState[];
  lines?: MapLine[];
  stops?: Stop[];
  points?: MapPoint[];
  selectedBusId?: number | null;
  fitKey?: string;
  onBusPress?: (busId: number) => void;
  onStopPress?: (stopId: number) => void;
  onMapPress?: (lat: number, lng: number) => void;
  height?: number | string;
}

const HTML = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#m{margin:0;height:100%;background:#e5e9f0}.b{position:relative;width:34px;height:34px}
.b i{position:absolute;left:3px;top:3px;width:26px;height:26px;border-radius:8px;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35);color:#fff;font:700 9px/26px sans-serif;text-align:center;font-style:normal}
.b em{position:absolute;right:-6px;top:-4px;background:#f97316;color:#fff;font:700 7px/1 sans-serif;padding:2px 3px;border-radius:3px;font-style:normal}</style>
</head><body><div id="m"></div><script>
var map=L.map('m',{zoomControl:false}).setView([31.5204,74.3587],12);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'}).addTo(map);
var layers={lines:L.layerGroup().addTo(map),stops:L.layerGroup().addTo(map),points:L.layerGroup().addTo(map),buses:L.layerGroup().addTo(map)};
var busMarkers={};
function send(o){window.ReactNativeWebView.postMessage(JSON.stringify(o))}
map.on('click',function(e){send({t:'map',lat:e.latlng.lat,lng:e.latlng.lng})});
window.setData=function(d){
  layers.lines.clearLayers();layers.stops.clearLayers();layers.points.clearLayers();
  (d.lines||[]).forEach(function(l){L.polyline(l.path,{color:l.color,weight:l.dim?3:6,opacity:l.dim?.35:.85}).addTo(layers.lines)});
  (d.stops||[]).forEach(function(s){L.circleMarker([s.lat,s.lng],{radius:6,color:'#173693',weight:3,fillColor:'#fff',fillOpacity:1}).bindTooltip(s.name).on('click',function(){send({t:'stop',id:s.id})}).addTo(layers.stops)});
  (d.points||[]).forEach(function(p){var c=p.kind==='origin'?'#16a34a':p.kind==='destination'?'#f97316':'#2563eb';L.circleMarker([p.lat,p.lng],{radius:9,color:'#fff',weight:3,fillColor:c,fillOpacity:1}).bindTooltip(p.label,{permanent:p.kind!=='me',direction:'top'}).addTo(layers.points)});
  var seen={};
  (d.buses||[]).forEach(function(b){ if(b.lat==null)return; seen[b.id]=1;
    var html='<div class="b" style="opacity:'+(b.faded?.55:1)+'"><i style="background:'+b.color+';'+(b.sel?'border-color:#f97316;border-width:3px':'')+'">BUS</i>'+(b.demo?'<em>DEMO</em>':'')+'</div>';
    var icon=L.divIcon({className:'',html:html,iconSize:[34,34],iconAnchor:[17,17]});
    var m=busMarkers[b.id];
    if(m){m.setLatLng([b.lat,b.lng]);m.setIcon(icon)}else{m=busMarkers[b.id]=L.marker([b.lat,b.lng],{icon:icon}).on('click',function(){send({t:'bus',id:b.id})}).addTo(layers.buses)}
  });
  Object.keys(busMarkers).forEach(function(k){if(!seen[k]){layers.buses.removeLayer(busMarkers[k]);delete busMarkers[k]}});
  if(d.fit){var pts=[];(d.lines||[]).filter(function(l){return!l.dim}).forEach(function(l){pts=pts.concat(l.path)});(d.points||[]).forEach(function(p){pts.push([p.lat,p.lng])});
    if(!pts.length)(d.stops||[]).forEach(function(s){pts.push([s.lat,s.lng])});
    if(pts.length>1)map.fitBounds(pts,{padding:[30,30],maxZoom:15});else if(pts.length==1)map.setView(pts[0],15);}
};
send({t:'ready'});
</script></body></html>`;

const COLORS: Record<string, string> = { active: "#173693", delayed: "#d97706", stale: "#94a3b8", offline: "#94a3b8", idle: "#0284c7", out_of_service: "#dc2626" };

export default function LiveMap(p: Props) {
  const ref = useRef<WebView>(null);
  const ready = useRef(false);
  const lastFit = useRef<string | undefined>(undefined);

  const push = () => {
    if (!ready.current) return;
    const fit = p.fitKey !== undefined && p.fitKey !== lastFit.current;
    lastFit.current = p.fitKey;
    const data = {
      fit,
      lines: p.lines || [],
      stops: (p.stops || []).map((s) => ({ id: s.id, lat: s.lat, lng: s.lng, name: s.name })),
      points: p.points || [],
      buses: (p.buses || []).map((b) => {
        const st = effectiveStatus(b);
        return { id: b.bus_id, lat: b.lat, lng: b.lng, color: COLORS[st] || "#173693", faded: st === "stale" || st === "offline", demo: b.is_demo, sel: b.bus_id === p.selectedBusId };
      }),
    };
    ref.current?.injectJavaScript(`window.setData(${JSON.stringify(data)});true;`);
  };

  useEffect(push);

  return (
    <View style={[styles.wrap, { height: p.height as number | undefined ?? "100%" }]}>
      <WebView
        ref={ref}
        source={{ html: HTML }}
        originWhitelist={["*"]}
        javaScriptEnabled
        onMessage={(e) => {
          const m = JSON.parse(e.nativeEvent.data);
          if (m.t === "ready") {
            ready.current = true;
            lastFit.current = undefined;
            push();
          } else if (m.t === "bus") p.onBusPress?.(m.id);
          else if (m.t === "stop") p.onStopPress?.(m.id);
          else if (m.t === "map") p.onMapPress?.(m.lat, m.lng);
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({ wrap: { width: "100%", overflow: "hidden", backgroundColor: "#e5e9f0" } });
