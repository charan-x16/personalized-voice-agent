"use client";

import { useSyncExternalStore } from "react";

const subscribe = () => () => {};
const clientSnapshot = () => false;
const serverSnapshot = () => true;

/** Stable UTC server markup, then the reader's own locale and timezone after hydration. */
export function LocalTime({ value, kind = "date" }: { value: string; kind?: "date" | "time" | "datetime" | "day" }) {
  const server = useSyncExternalStore(subscribe, clientSnapshot, serverSnapshot);
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return <span>Time unavailable</span>;
  const options: Intl.DateTimeFormatOptions = {
    ...(server ? { timeZone: "UTC" } : {}),
    ...(kind !== "time" ? { day: "numeric", month: "short", ...(kind === "day" ? { weekday: "long" } : { year: "numeric" }) } : {}),
    ...(kind === "time" || kind === "datetime" ? { hour: "numeric", minute: "2-digit", timeZoneName: "short" } : {}),
  };
  const formatter = new Intl.DateTimeFormat(server ? "en-IN" : undefined, options);
  return <time dateTime={value} title={`${date.toISOString()} · shown in ${formatter.resolvedOptions().timeZone}`}>{formatter.format(date)}</time>;
}
