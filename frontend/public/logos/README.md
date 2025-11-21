# Logo Placeholder

This directory is for service logos (SVG format recommended).

Currently the UI shows colored placeholder boxes with the first letter of each service name.

To add actual logos:
1. Add SVG files here named: `cloudflare.svg`, `aws.svg`, `azure.svg`, `gcp.svg`, `github.svg`, `datadog.svg`, `atlassian.svg`
2. Update logo paths in `src/types/index.ts` if using different filenames

The logos will automatically display in the agent list sidebar.
