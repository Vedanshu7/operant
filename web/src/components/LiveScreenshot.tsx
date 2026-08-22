import { useEffect, useState, type ReactElement } from "react";

import { useAuthedBlobUrl } from "@/hooks/useAuthedBlobUrl";

export interface LiveScreenshotProps {
  runId: string;
  version: number;
  running: boolean;
}

const POLL_MS = 5000;

export function LiveScreenshot({ runId, version, running }: LiveScreenshotProps): ReactElement {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setTick((t) => t + 1), POLL_MS);
    return () => clearInterval(id);
  }, [running]);

  // Only fetch once a screenshot has actually been captured (version > 0),
  // so a run that has not produced one yet does not spam 404s.
  const src = version > 0 ? `/runs/${runId}/screenshot` : null;
  const { url } = useAuthedBlobUrl(src, version * 100_000 + tick);

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-muted">
      {url ? (
        <img src={url} alt="Latest screenshot of the live session" className="block w-full" />
      ) : (
        <div className="flex h-40 items-center justify-center text-xs text-muted-foreground">
          {running ? "Waiting for screenshot…" : "No screenshot captured"}
        </div>
      )}
    </div>
  );
}
