export function containsSecretSentinel(payload: unknown, sentinels: string[]): boolean {
  const serialized = JSON.stringify(payload) ?? "";
  return sentinels.some((sentinel) =>
    serialized.includes(JSON.stringify(sentinel).slice(1, -1)),
  );
}
