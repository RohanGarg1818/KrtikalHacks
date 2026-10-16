"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "./ui";

// Leaflet touches `window`, so the map renders on the client only.
const PincodeMap = dynamic(() => import("./PincodeMap"), {
  ssr: false,
  loading: () => <Skeleton className="h-[460px] w-full" />,
});

export default PincodeMap;
