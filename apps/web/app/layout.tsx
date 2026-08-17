import type { Metadata } from "next";
import { MainNav } from "@/components/nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Certainti Tech Administration",
  description:
    "Internal portal for hardware assets, software licences, people, and access requests.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <div className="mx-auto flex min-h-screen max-w-6xl flex-col px-4 sm:px-6">
          <MainNav />
          <main className="flex-1 py-8">{children}</main>
          <footer className="border-t border-line py-6 text-sm text-muted">
            Certainti Tech Administration — internal use only.
          </footer>
        </div>
      </body>
    </html>
  );
}
