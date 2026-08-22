import { useMemo, useState, type ReactElement } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { useEvidence, useEvidenceText } from "@/api/queries";
import { Badge } from "@/components/Badge";
import { Card } from "@/components/Card";
import { ErrorBox } from "@/components/ErrorBox";
import { EventTimeline } from "@/components/EventTimeline";
import { Lightbox } from "@/components/Lightbox";
import { Loading } from "@/components/Loading";
import { PageHeader } from "@/components/PageHeader";
import { useAuthedBlobUrl } from "@/hooks/useAuthedBlobUrl";
import { formatBytes } from "@/lib/format";
import { parseJsonl } from "@/lib/jsonl";

export function EvidencePage(): ReactElement {
  const { runId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const selected = params.get("file");
  const listing = useEvidence(runId);
  const [lightbox, setLightbox] = useState<string | null>(null);

  const selectedFile = listing.data?.files.find((f) => f.path === selected) ?? null;
  const isText = selectedFile !== null && selectedFile.kind !== "png";
  const text = useEvidenceText(runId, isText ? selectedFile.path : null);
  const image = useAuthedBlobUrl(lightbox ? `/evidence/${runId}/files/${lightbox}` : null);
  const events = useMemo(
    () => (selectedFile?.kind === "jsonl" && text.data ? parseJsonl(text.data) : null),
    [selectedFile, text.data],
  );

  const select = (path: string | null): void => {
    const next = new URLSearchParams(params);
    if (path) next.set("file", path);
    else next.delete("file");
    setParams(next);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Evidence"
        description="The structured log and screenshots captured during the run."
        actions={
          <Link to={`/runs/${runId}`} className="font-mono text-xs text-primary hover:underline">
            {runId}
          </Link>
        }
      />
      <div className="grid gap-4 lg:grid-cols-[1fr_2fr]">
        <Card title="Files">
          {listing.isPending && <Loading />}
          <ErrorBox error={listing.error} />
          {listing.data && (
            <ul className="space-y-1">
              {listing.data.files.map((f) => (
                <li key={f.path}>
                  <button
                    type="button"
                    className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-accent ${selected === f.path ? "bg-muted" : ""}`}
                    onClick={() => (f.kind === "png" ? setLightbox(f.path) : select(f.path))}
                  >
                    <Badge>{f.kind}</Badge>
                    <span className="flex-1 truncate font-mono">{f.path}</span>
                    <span className="text-muted-foreground">{formatBytes(f.size)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title={selectedFile ? selectedFile.path : "Select a file"}>
          {!selectedFile && (
            <p className="text-sm text-muted-foreground">
              Click a file to view it. PNGs open in a lightbox.
            </p>
          )}
          {isText && text.isPending && <Loading />}
          <ErrorBox error={text.error} />
          {events && <EventTimeline events={events} />}
          {selectedFile && selectedFile.kind !== "jsonl" && text.data !== undefined && (
            <pre className="max-h-[70vh] overflow-auto rounded bg-zinc-100 p-2 font-mono text-xs dark:bg-muted">
              {text.data}
            </pre>
          )}
        </Card>
      </div>
      <Lightbox src={image.url} alt={lightbox ?? ""} onClose={() => setLightbox(null)} />
    </div>
  );
}
