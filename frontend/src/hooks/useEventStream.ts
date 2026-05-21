import { useEffect } from "react";

type Handler = (raw: string) => void;
type ErrorHandler = () => void;

// Per ADR-001 §6.5 — does NOT close() on transient errors; EventSource
// reconnects on its own. Caller may use `onError` to trigger resync.
export function useEventStream(url: string, onMessage: Handler, onError?: ErrorHandler): void {
  useEffect(() => {
    const source = new EventSource(url, { withCredentials: true });

    source.onmessage = (event) => {
      onMessage(event.data);
    };

    source.onerror = () => {
      onError?.();
    };

    return () => {
      source.close();
    };
  }, [url, onMessage, onError]);
}
