import "@testing-library/jest-dom";
import { renderHook, act } from "@testing-library/react";
import { useEventStream } from "../src/hooks/useEventStream";

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  withCredentials: boolean;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(url: string, init?: EventSourceInit) {
    this.url = url;
    this.withCredentials = !!init?.withCredentials;
    MockEventSource.instances.push(this);
  }
  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  (global as { EventSource: unknown }).EventSource = MockEventSource;
});

describe("useEventStream", () => {
  it("invokes onMessage with event data", () => {
    const handler = jest.fn();
    renderHook(() => useEventStream("/stream", handler));
    const inst = MockEventSource.instances[0];
    act(() => {
      inst.onmessage?.({ data: "hi" } as MessageEvent);
    });
    expect(handler).toHaveBeenCalledWith("hi");
  });

  it("does NOT close on transient error; calls onError if provided", () => {
    const handler = jest.fn();
    const onError = jest.fn();
    renderHook(() => useEventStream("/stream", handler, onError));
    const inst = MockEventSource.instances[0];
    act(() => {
      inst.onerror?.();
    });
    expect(inst.closed).toBe(false);
    expect(onError).toHaveBeenCalled();
  });

  it("closes on unmount", () => {
    const { unmount } = renderHook(() => useEventStream("/stream", jest.fn()));
    const inst = MockEventSource.instances[0];
    unmount();
    expect(inst.closed).toBe(true);
  });
});
