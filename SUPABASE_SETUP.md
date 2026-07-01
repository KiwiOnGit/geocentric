# Supabase server SDK setup

## 1. Install the SDK

```bash
npm install @supabase/server
```

## 2. Configure environment variables

Copy the real values from the Supabase dashboard's Connect dialog and place them in your shell or local environment:

```bash
export SUPABASE_URL="https://<project-ref>.supabase.co"
export SUPABASE_PUBLISHABLE_KEY="sb_publishable_<key>"
export SUPABASE_SECRET_KEY="sb_secret_<key>"
export SUPABASE_JWKS_URL="https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json"
```

Do not commit the secret key. A sample file is available at [.env.example](.env.example).

## 3. Use the SDK in a request handler

```ts
import { withSupabase } from "@supabase/server";

export default {
  fetch: withSupabase({ auth: "user" }, async (_req, ctx) => {
    const { data } = await ctx.supabase.from("todos").select();
    return Response.json(data);
  }),
};
```

## 4. Auth modes

- `"user"`: validates a JWT and provides `ctx.supabase`
- `"publishable"`: uses the publishable key
- `"secret"`: uses the secret key
- `"none"`: skips auth validation

On Supabase Edge Functions, the environment variables are injected automatically. For non-`"user"` auth modes, set `verify_jwt = false` in [supabase/config.toml](supabase/config.toml).
