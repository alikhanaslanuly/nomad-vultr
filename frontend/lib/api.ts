import { createMockApi } from "./mock/adapter";
import { createRealApi } from "./real-api";

export const isMock = process.env.NEXT_PUBLIC_MOCK === "1";
export const api = isMock
  ? createMockApi()
  : createRealApi(process.env.NEXT_PUBLIC_API_BASE || "/api");
