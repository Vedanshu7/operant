import type { SseEnvelope } from "@/api/types";

export function parseJsonl(text: string): SseEnvelope[] {
  const out: SseEnvelope[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const parsed = JSON.parse(trimmed) as Partial<SseEnvelope>;
      out.push({
        run_id: parsed.run_id ?? "",
        seq: typeof parsed.seq === "number" ? parsed.seq : out.length + 1,
        at: parsed.at ?? "",
        type: parsed.type ?? "event",
        summary: parsed.summary ?? "",
        data: parsed.data ?? {},
        run_status: parsed.run_status ?? "running",
        screenshot: parsed.screenshot ?? null,
      });
    } catch {
      out.push({
        run_id: "",
        seq: out.length + 1,
        at: "",
        type: "unparsed",
        summary: trimmed.slice(0, 200),
        data: {},
        run_status: "running",
        screenshot: null,
      });
    }
  }
  return out;
}
