"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useEffect, useMemo } from "react";
import { Circle, MapContainer, Marker, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { Heatmap, HeatmapPin } from "@/lib/types";
import { STATUS_META } from "./ui";
import { rupees } from "@/lib/format";

function pinIcon(status: string, selected: boolean) {
  const m = STATUS_META[status] ?? STATUS_META.stale;
  return L.divIcon({
    className: "",
    html: `<div class="ss-pin ${status}${selected ? " selected" : ""}" aria-label="${m.label}">${m.icon}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

function FitBounds({ pins }: { pins: HeatmapPin[] }) {
  const map = useMap();
  const key = pins.map((p) => p.pincode).join(",");
  useEffect(() => {
    const pts = pins.filter((p) => p.lat != null && p.lng != null).map((p) => [p.lat!, p.lng!] as [number, number]);
    if (pts.length) map.fitBounds(pts, { padding: [40, 40], maxZoom: 13 });
    // Refit only when the set of pincodes changes, not on every status update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map]);
  return null;
}

export default function PincodeMap({
  pins,
  hotZones = [],
  selected,
  onSelect,
  showRival = false,
  height = 460,
  interactive = true,
}: {
  pins: HeatmapPin[];
  hotZones?: Heatmap["hot_zones"];
  selected?: string | null;
  onSelect?: (pincode: string) => void;
  showRival?: boolean;
  height?: number;
  interactive?: boolean;
}) {
  const located = useMemo(() => pins.filter((p) => p.lat != null && p.lng != null), [pins]);
  return (
    <MapContainer
      center={[28.56, 77.21]}
      zoom={12}
      style={{ height, width: "100%" }}
      scrollWheelZoom={interactive}
      dragging={interactive}
      zoomControl={interactive}
      attributionControl={interactive}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <FitBounds pins={located} />
      {hotZones.map((z, i) => (
        <Circle
          key={i}
          center={[z.lat, z.lng]}
          radius={900 + z.count * 250}
          pathOptions={{ color: "#1e2a3a", weight: 2, dashArray: "6 6", fillColor: "#e6c98f", fillOpacity: 0.28, className: "ss-hotzone" }}
        />
      ))}
      {located.map((p) => (
        <Marker
          key={`${p.pincode}-${p.status}-${selected === p.pincode}`}
          position={[p.lat!, p.lng!]}
          icon={pinIcon(p.status, selected === p.pincode)}
          eventHandlers={{ click: () => onSelect?.(p.pincode) }}
        >
          <Tooltip direction="top" offset={[0, -14]} permanent={showRival}>
            <div className="text-xs">
              <b>{p.pincode}</b> {p.area}
              <br />
              {STATUS_META[p.status]?.label ?? p.status}
              {showRival && (
                <>
                  <br />
                  You {rupees(p.price)} · Rival {rupees(p.rival_price)}
                </>
              )}
            </div>
          </Tooltip>
        </Marker>
      ))}
    </MapContainer>
  );
}
