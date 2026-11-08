import { File as NodeFile } from "node:buffer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readUpload } from "@/features/read-upload";

beforeEach(() => vi.stubGlobal("File", NodeFile));
afterEach(() => vi.unstubAllGlobals());

describe("artifact upload", () => {
  it("preserves the Python filename and source instead of renaming to shell", async () => {
    const file = new File(["print('hello')"], "script.py");
    await expect(readUpload(file)).resolves.toEqual({
      filename: "script.py",
      content: "print('hello')",
      inputType: "paste",
    });
  });
  it("transmits binary ZIP bytes losslessly as base64", async () => {
    const bytes = new Uint8Array([80, 75, 3, 4, 0, 255, 128]);
    const upload = await readUpload(new File([bytes], "package.zip"));
    expect(upload.inputType).toBe("zip");
    expect(Uint8Array.from(atob(upload.content), (char) => char.charCodeAt(0))).toEqual(
      bytes,
    );
    expect(upload.filename).toBe("package.zip");
  });
  it("rejects unsupported, oversized and undisplayable text before submission", async () => {
    await expect(readUpload(new File(["x"], "image.png"))).rejects.toThrow("Unsupported");
    await expect(
      readUpload(new File([new Uint8Array(2 * 1024 * 1024 + 1)], "large.zip")),
    ).rejects.toThrow("2 MiB");
    await expect(readUpload(new File(["x".repeat(200001)], "large.py"))).rejects.toThrow(
      "200,000",
    );
  });
});
