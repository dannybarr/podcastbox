import { Suspense } from "react";
import { Home } from "@/components/home";
import { Typography } from "@/ui";

export default function Page() {
  return (
    <Suspense
      fallback={
        <div className="page-frame reading-column">
          <Typography variant="body-2" tag="p">
            Loading chains…
          </Typography>
        </div>
      }
    >
      <Home />
    </Suspense>
  );
}
