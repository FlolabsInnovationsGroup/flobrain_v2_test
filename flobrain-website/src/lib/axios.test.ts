import { afterEach, describe, expect, it, vi } from "vitest";

describe("getApiBaseUrl", () => {
  afterEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  it("uses NEXT_PUBLIC_API_URL when set", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://example.test/");
    const { getApiBaseUrl } = await import("./axios");
    expect(getApiBaseUrl()).toBe("https://example.test");
  });

  it("defaults to local Django in development", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "");
    vi.stubEnv("NODE_ENV", "development");
    const { getApiBaseUrl } = await import("./axios");
    expect(getApiBaseUrl()).toBe("http://127.0.0.1:8000");
  });
});
