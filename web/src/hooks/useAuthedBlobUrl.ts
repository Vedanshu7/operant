import { useEffect, useState } from "react";

import { fetchRaw } from "@/api/client";

export interface AuthedBlob {
  url: string | null;
  error: string | null;
}

export function useAuthedBlobUrl(path: string | null, version = 0): AuthedBlob {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!path) {
      setUrl(null);
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | null = null;
    fetchRaw(path, { signal: controller.signal })
      .then((res) => res.blob())
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
        setError(null);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "failed to load");
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path, version]);

  return { url, error };
}
