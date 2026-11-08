import { expect, it } from "vitest";
import { containsSecretSentinel } from "@/test-support/secret-scan";

it("detects fake secret sentinels even when JSON escaping changes their representation", () => {
  for (const sentinel of [
    "FAKE-SENTINEL-plain",
    'FAKE-"-SENTINEL',
    "FAKE-\n-SENTINEL",
    "FAKE-\\-SENTINEL",
  ]) {
    expect(
      containsSecretSentinel({ nested: [{ text: `prefix ${sentinel} suffix` }] }, [
        sentinel,
      ]),
    ).toBe(true);
    expect(
      containsSecretSentinel({ nested: [{ text: "unrelated output" }] }, [sentinel]),
    ).toBe(false);
  }
});
