import { useEffect, useMemo, useRef, useState, type ReactElement } from "react";

import type { SseEnvelope } from "@/api/types";

import { Button } from "./Button";
import { EventRow } from "./EventRow";

export interface EventTimelineProps {
  events: SseEnvelope[];
  live?: boolean;
  windowSize?: number;
}

export function EventTimeline({
  events,
  live = false,
  windowSize = 300,
}: EventTimelineProps): ReactElement {
  const [filter, setFilter] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const types = useMemo(() => Array.from(new Set(events.map((e) => e.type))).sort(), [events]);
  const filtered = useMemo(
    () => (filter ? events.filter((e) => e.type === filter) : events),
    [events, filter],
  );
  const visible = showAll || filtered.length <= windowSize ? filtered : filtered.slice(-windowSize);
  const hidden = filtered.length - visible.length;

  useEffect(() => {
    if (live && autoScroll) bottomRef.current?.scrollIntoView({ block: "nearest" });
  }, [visible.length, live, autoScroll]);

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <label className="inline-flex items-center gap-1">
          Filter
          <select
            aria-label="Filter by event type"
            className="input w-auto py-0.5"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="">all types</option>
            {types.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        {live && (
          <Button
            size="sm"
            variant={autoScroll ? "secondary" : "primary"}
            onClick={() => setAutoScroll((a) => !a)}
          >
            {autoScroll ? "Pause auto-scroll" : "Resume auto-scroll"}
          </Button>
        )}
        <span className="ml-auto text-muted-foreground">
          {filtered.length} event{filtered.length === 1 ? "" : "s"}
        </span>
      </div>
      {hidden > 0 && (
        <button
          type="button"
          className="mb-1 text-xs text-primary hover:underline"
          onClick={() => setShowAll(true)}
        >
          Show {hidden} earlier event{hidden === 1 ? "" : "s"}
        </button>
      )}
      <ul
        className="max-h-[70vh] flex-1 overflow-y-auto pr-1"
        aria-live={live ? "polite" : undefined}
      >
        {visible.length === 0 && (
          <li className="py-6 text-center text-sm text-muted-foreground">No events yet.</li>
        )}
        {visible.map((ev, i) => (
          <EventRow key={`${ev.seq}-${ev.type}`} event={ev} last={i === visible.length - 1} />
        ))}
        <div ref={bottomRef} />
      </ul>
    </div>
  );
}
