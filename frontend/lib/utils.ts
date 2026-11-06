import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...values: ClassValue[]) {
  return twMerge(clsx(values));
}
export function date(value?: string, time = false) {
  return value
    ? new Intl.DateTimeFormat("en-PK", {
        timeZone: "Asia/Karachi",
        day: "2-digit",
        month: "short",
        year: "numeric",
        ...(time ? { hour: "2-digit", minute: "2-digit" } : {}),
      }).format(new Date(value))
    : "Never signed in";
}
export function initials(name: string) {
  return name
    .split(" ")
    .slice(0, 2)
    .map((s) => s[0])
    .join("");
}
