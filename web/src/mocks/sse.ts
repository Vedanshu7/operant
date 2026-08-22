import type { SseEnvelope } from "@/api/types";

export function encodeSseMessage(env: SseEnvelope): string {
  return `id: ${env.seq}\nevent: ${env.type}\ndata: ${JSON.stringify(env)}\n\n`;
}

export function sseStream(events: SseEnvelope[], intervalMs: number): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  return new ReadableStream<Uint8Array>({
    start(controller) {
      const push = (): void => {
        const ev = events[i];
        if (!ev) {
          controller.close();
          return;
        }
        controller.enqueue(encoder.encode(encodeSseMessage(ev)));
        i += 1;
        timer = setTimeout(push, intervalMs);
      };
      push();
    },
    cancel() {
      if (timer !== undefined) clearTimeout(timer);
    },
  });
}
