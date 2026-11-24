import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: { default: "Drivewell · A professional driver for your car", template: "%s · Drivewell" },
  description: "Request a professional driver for your own car in Bengaluru. Book by the hour, half day or full day.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><Providers>{children}</Providers></body></html>;
}
