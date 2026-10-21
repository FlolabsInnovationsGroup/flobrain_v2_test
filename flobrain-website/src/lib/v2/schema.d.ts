/**
 * Minimal V2 OpenAPI types. Regenerate with `npm run gen:api` once
 * openapi-typescript is installed and a schema file is exported.
 */
export interface paths {
  "/api/v2/me": {
    get: {
      responses: {
        200: {
          content: {
            "application/json": components["schemas"]["Me"];
          };
        };
      };
    };
  };
  "/api/v2/auth/signin": {
    post: {
      requestBody: {
        content: {
          "application/json": { email: string; password: string };
        };
      };
      responses: {
        200: {
          content: {
            "application/json": components["schemas"]["TokenPair"];
          };
        };
      };
    };
  };
}

export interface components {
  schemas: {
    Me: {
      id: string;
      email: string;
      username: string | null;
      user_type: string;
      must_change_password: boolean;
      is_platform_admin: boolean;
    };
    TokenPair: {
      access: string;
      refresh: string;
      user_id: string;
      must_change_password: boolean;
    };
  };
}
