// Pure sequence-gap / duplicate detector for the WS stream. Kept framework-free
// so it is trivially unit-testable. The server sends a per-connection monotonic
// `seq`; a gap means we missed messages and should recover state via REST.

export type SeqResult = "ok" | "duplicate" | "gap" | "reset";

export class SequenceTracker {
  private last: number | null = null;

  /** Feed the next envelope's seq; returns how it relates to the stream. */
  observe(seq: number): SeqResult {
    if (this.last === null) {
      this.last = seq;
      return "ok";
    }
    if (seq === this.last + 1) {
      this.last = seq;
      return "ok";
    }
    if (seq <= this.last) {
      // seq 0 after a higher value means the server restarted the connection.
      if (seq === 0) {
        this.last = 0;
        return "reset";
      }
      return "duplicate";
    }
    // seq > last + 1 -> we missed (seq - last - 1) messages.
    this.last = seq;
    return "gap";
  }

  reset(): void {
    this.last = null;
  }

  get lastSeq(): number | null {
    return this.last;
  }
}
