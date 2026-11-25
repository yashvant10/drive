"use client";

import Link from "next/link";

export default function PortalError({reset}: {reset:()=>void}) {
  return <main className="wrap section subpage">
    <h1 className="page-title">Workspace temporarily unavailable</h1>
    <p>The account service did not respond. Try again in a moment.</p>
    <div className="flex flex-wrap gap-3 mt-4">
      <button className="button" onClick={reset}>Try again</button>
      <Link className="button secondary" href="/">Return to Drivewell</Link>
    </div>
  </main>;
}
