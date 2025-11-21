# GWEN Frontend - Multi-Cloud Status Monitor

Matrix-themed React dashboard for monitoring cloud service status across multiple providers.

## Tech Stack

- **React 18.3.1** - UI framework
- **TypeScript 5.2.2** - Type safety
- **Vite 5.3.1** - Build tool
- **Tailwind CSS 3.4.4** - Styling with custom Matrix theme
- **Axios 1.7.2** - HTTP client

## Features

- **Three-Pane Layout**: Agent list (left), dashboard/detail view (center), logs (right)
- **Matrix Terminal Aesthetic**: Neon green (#00FF41) on dark background with glow effects
- **Real-time Polling**: Updates every 3 seconds
- **14-Day History**: Shows comprehensive incident and maintenance data
- **State Visualization**: Color-coded badges (idle/thinking/completed/warning/error)

## Monitored Services

1. Cloudflare (CDN/DNS)
2. AWS (Health Dashboard)
3. Azure (Public Cloud)
4. GCP (Cloud Platform)
5. GitHub (Services)
6. Datadog (Monitoring)
7. Atlassian (Jira/Confluence)

## Setup

### Prerequisites

- Node.js 18+ 
- npm or yarn
- Backend running on `http://localhost:8000`

### Installation

```bash
# Install dependencies
npm install

# Run development server
npm run dev
```

The frontend will start on `http://localhost:3000` with API proxy to backend.

### Build for Production

```bash
npm run build
npm run preview
```

## Project Structure

```
frontend/
├── src/
│   ├── api/
│   │   └── index.ts          # API integration layer
│   ├── components/
│   │   ├── AgentCard.tsx     # Individual agent list item
│   │   ├── AgentList.tsx     # Left sidebar with all agents
│   │   ├── AgentDetailView.tsx  # Center pane for selected agent
│   │   ├── AgentLogs.tsx     # Right pane logs display
│   │   └── DashboardView.tsx # Center pane default view
│   ├── types/
│   │   └── index.ts          # TypeScript interfaces
│   ├── App.tsx               # Main application component
│   ├── main.tsx              # React entry point
│   └── index.css             # Global styles with Matrix theme
├── index.html
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
└── package.json
```

## API Endpoints

- `GET /api/agent-status` - Current status of all agents
- `GET /api/agent-logs/:agentName` - Detailed logs for specific agent
- `POST /api/retrieve-status` - Trigger full orchestrator report

## Matrix Theme

Custom Tailwind colors:
- `matrix-green`: #00FF41 (primary accent)
- `matrix-dark`: #0D0208 (panel background)
- `matrix-darker`: #000000 (app background)
- `matrix-gray`: #1a1a1a (hover states)

Custom animations:
- `animate-pulse`: 2s opacity pulse for "thinking" state
- `animate-scan`: 4s scanning line effect

Status badge classes:
- `.status-idle` - Gray (inactive)
- `.status-thinking` - Blue (processing)
- `.status-completed` - Green (success)
- `.status-warning` - Yellow (minor issues)
- `.status-error` - Red (critical issues)

## Development

```bash
# Start dev server with hot reload
npm run dev

# Type checking
npm run build  # TypeScript errors will be shown

# Lint code
npm run lint
```

## Notes

- Backend must be running on port 8000 for API proxy to work
- Logos currently show as colored placeholders (first letter)
- CSS lint errors for @tailwind directives are expected (PostCSS processes them)
- Polling intervals: 3 seconds for status/logs updates
