# GWEN Quick Start Guide

Get the multi-cloud status monitoring dashboard running in 2 minutes.

## Prerequisites

- **Python 3.13+** (backend)
- **Node.js 18+** (frontend)
- **npm** or **yarn**

## Setup

### 1. Backend Setup (Python/FastAPI)

```bash
# Install Python dependencies
pip install -r requirements.txt

# Start the backend server
python main.py
```

Backend will run on **http://localhost:8000**

### 2. Frontend Setup (React/TypeScript)

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Frontend will run on **http://localhost:3000** with automatic backend proxy.

## Access the Dashboard

Open your browser to: **http://localhost:3000**

You'll see:
- **Left Panel**: List of 7 monitored services (Cloudflare, AWS, Azure, GCP, GitHub, Datadog, Atlassian)
- **Center Panel**: Dashboard overview or detailed agent view (click an agent to see details)
- **Right Panel**: Live logs for selected agent

## What You'll See

The dashboard monitors:
1. **Cloudflare** - CDN/DNS status + scheduled maintenance
2. **AWS** - Health Dashboard events
3. **Azure** - Public cloud status (RSS feed)
4. **GCP** - Cloud Platform incidents
5. **GitHub** - Services status
6. **Datadog** - Monitoring platform status
7. **Atlassian** - Jira/Confluence/Bitbucket status

Each agent shows:
- **Current status** (idle/thinking/completed/warning/error)
- **14-day incident history**
- **Scheduled maintenance** (Cloudflare only currently)
- **Detailed logs** with execution times
- **Key metrics** (incident counts, status indicators)

## Features

✨ **Matrix Terminal Aesthetic**: Dark theme with neon green (#00FF41), monospace fonts, glow effects  
🔄 **Real-time Updates**: Polls every 3 seconds  
⏱️ **Auto-Retrieve**: Optional automatic status checks every 5 minutes  
🎯 **Priority Sorting**: Non-operational services automatically appear first  
🏢 **Company Logos**: Authentic brand logos with optimized visibility  
📊 **Comprehensive Data**: 14-day history, no data consolidation  
📋 **Human-Readable Metrics**: Formatted data with clear status descriptions  
🎨 **Color-coded States**: Visual indication of agent status  
📝 **Live Logs**: See exactly what each agent is doing  

## Architecture

```
Backend (Port 8000)          Frontend (Port 3000)
┌─────────────────┐         ┌──────────────────┐
│   FastAPI App   │◄────────│   React + Vite   │
│                 │  Proxy  │                  │
│ 7 Agent Workers │  /api   │  Matrix Theme UI │
└─────────────────┘         └──────────────────┘
```

## API Endpoints

The backend exposes:
- `GET /agent-status` - All agent states
- `GET /agent-logs/{agent_name}` - Detailed logs
- `POST /retrieve-status` - Trigger full status check
- `GET /health` - Health check

Frontend automatically calls these via Vite proxy.

## Development Workflow

### Terminal 1 - Backend
```bash
python main.py
# Backend running on http://localhost:8000
```

### Terminal 2 - Frontend
```bash
cd frontend
npm run dev
# Frontend running on http://localhost:3000
```

### Making Changes

**Backend**: Python changes auto-reload with uvicorn  
**Frontend**: React changes hot-reload with Vite HMR  

## Troubleshooting

### Backend won't start
- Check Python version: `python --version` (need 3.13+)
- Install dependencies: `pip install -r requirements.txt`

### Frontend won't start
- Check Node version: `node --version` (need 18+)
- Delete `node_modules` and reinstall: `rm -rf node_modules && npm install`

### Frontend can't connect to backend
- Verify backend is running on port 8000
- Check Vite proxy config in `frontend/vite.config.ts`
- Look for CORS errors in browser console

### CSS/Tailwind not working
- Run `npm install` to ensure PostCSS and Tailwind are installed
- Check `tailwind.config.js` and `postcss.config.js` exist
- Restart Vite dev server

## Next Steps

1. **Explore Features**: Click the "● AUTO-RETRIEVE: OFF" button to enable 5-minute automatic updates
2. **Customize Theme**: Edit `frontend/tailwind.config.js` for different colors
3. **Add More Agents**: Create new agent in `agents/` directory
4. **Production Deploy**: 
   - Backend: `uvicorn main:app --host 0.0.0.0 --port 8000`
   - Frontend: `npm run build` then serve `dist/` folder

## Production Build

```bash
# Backend (no build needed)
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

# Frontend
cd frontend
npm run build
# Serve the dist/ folder with any static file server
npm run preview  # Or use nginx, Apache, etc.
```

## File Structure

```
gwen/
├── agents/               # 7 monitoring agents
├── orchestrator/         # Agent coordination
├── common/              # Shared utilities
├── frontend/            # React dashboard
│   ├── src/
│   │   ├── components/  # UI components
│   │   ├── api/        # Backend integration
│   │   ├── types/      # TypeScript definitions
│   │   └── App.tsx     # Main app
│   └── package.json
├── main.py             # FastAPI server
├── requirements.txt    # Python deps
└── README.md          # Full documentation
```

## Support

- Full docs: See `README.md`
- Frontend docs: See `frontend/README.md`
- Issues: Check browser console + backend logs

---

**You're ready!** 🚀 Both services should be running and the dashboard accessible at http://localhost:3000
