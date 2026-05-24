# PursuitDesk Frontend

Static Cloudflare Pages dashboard for the PursuitDesk demo.

Cloudflare Pages Git settings:

- Root directory: `frontend`
- Build command: leave blank
- Build output directory: `.`

The dashboard calls the backend configured in `frontend/config.js`. If that file is removed or the value is blank, the page falls back to local demo data so the deployment remains usable before the AWS API Gateway stack is live.
