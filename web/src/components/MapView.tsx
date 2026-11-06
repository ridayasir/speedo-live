"use client";

import dynamic from "next/dynamic";
import type { MapProps } from "./LeafletMap";

const LeafletMap = dynamic(() => import("./LeafletMap"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-slate-200" aria-label="Loading map" />,
});

export type { MapProps, MapRoute } from "./LeafletMap";

export default function MapView(props: MapProps) {
  return <LeafletMap {...props} />;
}
