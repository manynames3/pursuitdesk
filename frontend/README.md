# GovCon CaptureOS Frontend

Static Cloudflare Pages dashboard for the GovCon CaptureOS demo.

Cloudflare Pages Git settings:

- Root directory: `frontend`
- Build command: leave blank
- Build output directory: `.`

The dashboard calls the backend at `window.CAPTUREOS_API_BASE_URL` when that value is set. Without it, the page falls back to local demo data so the deployment remains usable before the AWS API Gateway stack is live.
