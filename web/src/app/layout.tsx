import type { Metadata } from "next";
import "@fontsource-variable/fraunces";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/inter/900.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import { Shell } from "@/components/shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "PodcastBox",
  description: "Turn email chains into podcasts. Privately.",
  openGraph: {
    title: "PodcastBox by DB Labs",
    description: "Turn email chains into podcasts. Privately.",
    images: ["/og.png"],
  },
};

const themeBoot = `(function(){try{var t=localStorage.getItem("podcastbox-theme")||localStorage.getItem("inbox-brief-theme");if(t==="dark"||(t!=="light"&&window.matchMedia("(prefers-color-scheme: dark)").matches)){document.documentElement.classList.add("dark");}}catch(e){}})();`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-GB" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBoot }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
