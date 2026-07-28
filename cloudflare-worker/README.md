# Kumamoto news trigger

Cloudflare Worker that starts the GitHub Actions collection workflow:

- every 5 minutes with a Cron Trigger;
- on demand from the public site's refresh button;
- with email enabled only at minute `00` and `30`.

## Required secret

Configure `GITHUB_TOKEN` as an encrypted Worker secret. Use a fine-grained
GitHub personal access token restricted to `yagiharuka/kumamoto` with
**Actions: Read and write** permission.

Do not put the token in `wrangler.jsonc`, the website JavaScript, or GitHub.

## Deploy

The repository's `Deploy Cloudflare Worker` GitHub Actions workflow deploys
the Worker without exposing credentials. Configure these repository secrets:

- `CLOUDFLARE_API_TOKEN`: Cloudflare's **Edit Cloudflare Workers** API token;
- `CLOUDFLARE_ACCOUNT_ID`: the target Cloudflare account ID;
- `WORKER_GITHUB_TOKEN`: a fine-grained GitHub token restricted to this
  repository with **Actions: Read and write**.

Then manually run `Deploy Cloudflare Worker` from the Actions tab.

For a local deployment, run from this directory:

```sh
npx wrangler deploy
npx wrangler secret put GITHUB_TOKEN
```

After deployment, replace `REPLACE_ME` in `docs/app.js` with the Worker's
actual `workers.dev` account subdomain.
