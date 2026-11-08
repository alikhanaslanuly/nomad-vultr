export async function readUpload(
  file: File,
): Promise<{ filename: string; content: string; inputType: "paste" | "zip" }> {
  if (file.size > 2 * 1024 * 1024) throw new Error("Upload must not exceed 2 MiB.");
  if (!/\.(zip|py|sh|bash|js|mjs|cjs|json)$/i.test(file.name))
    throw new Error("Unsupported file extension.");
  if (!file.name.toLowerCase().endsWith(".zip")) {
    const content = await file.text();
    if (content.length > 200000)
      throw new Error("Source text exceeds 200,000 characters.");
    return { filename: file.name, content, inputType: "paste" };
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192)
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  return { filename: file.name, content: btoa(binary), inputType: "zip" };
}
