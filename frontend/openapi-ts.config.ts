import { defineConfig } from "@hey-api/openapi-ts";

/** Backend OpenAPI URL; ensure the API service is running before generating. */
const apiBase = (
  process.env.OPENAPI_URL ??
  process.env.API_BASE ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://localhost:8000"
).replace(/\/$/, "");

export default defineConfig({
  input: {
    path: `${apiBase}/openapi.json`,
    watch: process.env.OPENAPI_WATCH === "1",
  },
  output: "./lib/api/generated",
  plugins: ["@hey-api/typescript", "@hey-api/sdk", "@hey-api/client-fetch"],
});
