# Gwen Multi-Agent System

A production-ready, async multi-agent orchestration system built with Python 3.10+ and FastAPI. Gwen provides unified monitoring and management across multiple cloud services and platforms.

## 🏗️ Architecture

```
gwen/
├── agents/              # Primary agent implementations
│   ├── base.py         # Base agent class with common functionality
│   ├── cloudflare.py   # Cloudflare DNS/CDN/Security monitoring
│   ├── aws.py          # AWS Health Dashboard monitoring
│   ├── azure.py        # Azure public cloud status (RSS feed)
│   ├── gcp.py          # Google Cloud Platform monitoring
│   ├── atlassian.py    # Jira & Confluence integration
│   ├── github.py       # GitHub repository and CI/CD monitoring
│   └── datadog.py      # Infrastructure and APM monitoring
├── orchestrator/        # Agent orchestration logic
│   └── orchestrator.py # Concurrent execution and state management
├── common/             # Shared utilities and models
│   ├── models.py       # Pydantic models for status and reports
│   ├── config.py       # Settings and environment configuration
│   └── logging.py      # Logging utilities
├── frontend/           # React/TypeScript UI (Matrix theme)
│   ├── src/
│   │   ├── components/ # React components (AgentList, Dashboard, Logs)
│   │   ├── api/        # API integration layer
│   │   ├── types/      # TypeScript interfaces
│   │   └── App.tsx     # Main application
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── main.py             # FastAPI application and endpoints
├── requirements.txt    # Python dependencies
└── .env.example        # Environment configuration template
```

## 🚀 Features

- **Async Multi-Agent Execution**: Concurrent execution of multiple monitoring agents
- **Matrix-Themed Dashboard**: React+TypeScript frontend with retro terminal aesthetic
- **14-Day History Window**: Comprehensive incident and maintenance tracking
- **Scheduled Maintenance Detection**: Tracks in-progress and upcoming maintenance windows
- **Dashboard-Ready State**: In-memory state management for real-time visualization
- **RESTful API**: FastAPI endpoints for triggering reports and retrieving status
- **Real-time Polling**: Frontend updates every 3 seconds
- **Auto-Retrieve**: Optional automatic status retrieval every 5 minutes
- **Priority Sorting**: Non-operational services automatically appear first in dashboard
- **Company Logos**: Authentic brand logos with optimized visibility
- **Three-Pane Layout**: Agent list, dashboard/detail view, and live logs
- **Human-Readable Data**: Formatted metrics with clear status descriptions
- **Modular Design**: Easy to extend with new agents
- **Comprehensive Logging**: Detailed execution logs and error handling
- **Type Safety**: Full type hints (Python) and TypeScript (Frontend)

## 📋 Prerequisites

- Python 3.13 or higher
- Node.js 18+ and npm (for frontend)
- pip for Python dependency management
- API credentials for services you want to monitor (optional - agents use public status pages)

## 🔧 Installation

1. **Clone or create the project structure**:
```bash
mkdir gwen && cd gwen
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Configure environment variables**:
```bash
cp .env.example .env
# Edit .env with your API credentials
```

## 🏃 Running the Application

### Backend (Python/FastAPI)

**Development Mode**:
```bash
python main.py
```

**Production Mode**:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

The backend API will be available at `http://localhost:8000`

### Frontend (React/TypeScript)

**Setup**:
```bash
cd frontend
npm install
```

**Development Mode**:
```bash
npm run dev
```

The frontend will be available at `http://localhost:3000` with automatic proxy to backend.

**Production Build**:
```bash
npm run build
npm run preview
```

### Full Stack Development

1. Start backend (terminal 1):
   ```bash
   python main.py
   ```

2. Start frontend (terminal 2):
   ```bash
   cd frontend
   npm run dev
   ```

3. Open browser to `http://localhost:3000`

## 📡 API Endpoints

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | System info and available endpoints |
| `/health` | GET | Health check for monitoring |
| `/retrieve-status` | POST | Execute all agents and get aggregated status |
| `/agent-status` | GET | Get current status of all agents |
| `/agent-status/{name}` | GET | Get status for specific agent |
| `/agent-logs/{name}` | GET | Get detailed logs for specific agent |
| `/execution-history` | GET | Get recent execution history |
| `/agents` | GET | List all available agents |
| `/agents/{name}/execute` | POST | Execute a single agent |

### Example Usage

#### Execute All Agents
```bash
curl -X POST http://localhost:8000/retrieve-status
```

#### Get All Agent Status
```bash
curl http://localhost:8000/agent-status
```

#### Get Specific Agent Logs
```bash
curl http://localhost:8000/agent-logs/CloudflareAgent
```

## 🎯 Agent Capabilities

### CloudflareAgent
- Status page monitoring (status.cloudflare.com)
- Incident tracking (14-day history)
- Scheduled maintenance detection with in-progress tracking
- Component status monitoring

### AWSAgent
- AWS Health Dashboard events
- Service health monitoring
- Event history (14 days)
- Regional status tracking

### AzureAgent
- Azure public cloud status (RSS feed: azure.status.microsoft/en-us/status/feed/)
- Service incident tracking
- Historical incident data (14 days)
- All Azure services monitoring

### GCPAgent
- Google Cloud Platform status monitoring
- Incident filtering (14-day history)
- Service health tracking
- Multi-region monitoring

### AtlassianAgent
- Atlassian status page monitoring
- Jira/Confluence/Bitbucket status
- Incident history (14 days)
- Component-level tracking

### GitHubAgent
- GitHub Services status (githubstatus.com)
- Incident tracking (14 days)
- GitHub Actions, API, Git operations status
- Historical incident data

### DatadogAgent
- Datadog status page monitoring (status.datadoghq.com)
- Infrastructure monitoring status
- Incident history (14 days)
- Service health tracking

## 🔌 Integration Points

The scaffold includes placeholders for real API integrations. To connect real services:

1. **Install service-specific SDKs**:
```bash
# Examples
pip install cloudflare
pip install azure-mgmt-resource azure-identity
pip install atlassian-python-api
pip install PyGithub
pip install datadog-api-client
```

2. **Update agent implementations**:
- Replace `simulate_api_call()` with actual API calls
- Implement authentication in `initialize()` methods
- Add error handling for service-specific exceptions

## 📊 Dashboard Integration

The system is designed for easy dashboard integration:

### Frontend Structure
```javascript
// Example React component structure
const Dashboard = () => {
  const [agents, setAgents] = useState({});
  
  // Poll agent status
  useEffect(() => {
    const interval = setInterval(async () => {
      const response = await fetch('/agent-status');
      const data = await response.json();
      setAgents(data);
    }, 5000);
    return () => clearInterval(interval);
  }, []);
  
  return (
    <div className="dashboard">
      <AgentList agents={agents} />      // Left pane
      <AgentDetails selected={selected} /> // Middle pane
      <ExecutionHistory />                 // Right pane
    </div>
  );
};
```

## 🔐 Authentication (To Implement)

Add authentication middleware:
```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    # Verify token logic
    if not verify_jwt(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return token

# Apply to endpoints
@app.post("/retrieve-status", dependencies=[Depends(verify_token)])
async def retrieve_status():
    # ... existing logic
```

## 🧪 Testing

Create test files:
```python
# tests/test_agents.py
import pytest
from agents import CloudflareAgent

@pytest.mark.asyncio
async def test_cloudflare_agent():
    agent = CloudflareAgent()
    status = await agent.get_status()
    assert status.agent_name == "CloudflareAgent"
    assert status.state in ["completed", "warning", "error"]
```

Run tests:
```bash
pytest tests/ -v --asyncio-mode=auto
```

## 📝 Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `CLOUDFLARE_API_KEY` | Cloudflare API key | No |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID | No |
| `ATLASSIAN_API_TOKEN` | Atlassian API token | No |
| `GITHUB_TOKEN` | GitHub personal access token | No |
| `DATADOG_API_KEY` | Datadog API key | No |
| `AGENT_TIMEOUT_SECONDS` | Max execution time per agent | No (default: 30) |
| `MAX_CONCURRENT_AGENTS` | Max agents running simultaneously | No (default: 5) |

## 🔄 Extending the System

### Adding a New Agent

1. Create new agent file in `agents/`:
```python
from .base import BaseAgent

class NewServiceAgent(BaseAgent):
    def __init__(self):
        super().__init__("NewServiceAgent")
    
    async def _execute_task(self) -> Dict[str, Any]:
        # Implement service-specific logic
        return {"data": "placeholder"}
```

2. Register in orchestrator:
```python
# In orchestrator/orchestrator.py
self.agents = {
    # ... existing agents
    "NewServiceAgent": NewServiceAgent()
}
```

## 🐛 Troubleshooting

### Common Issues

1. **Agent Timeout**: Increase `AGENT_TIMEOUT_SECONDS` in .env
2. **Rate Limiting**: Adjust `MAX_CONCURRENT_AGENTS` to reduce parallel calls
3. **Memory Usage**: Implement cleanup in long-running scenarios
4. **API Errors**: Check credentials and API quotas

## 📈 Performance Optimization

- Use connection pooling for API clients
- Implement caching for frequently accessed data
- Add Redis for distributed state management
- Use background tasks for non-critical operations

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## 📄 License

MIT License - feel free to use for personal or commercial projects.

## 🆘 Support

For issues or questions, please create an issue in the repository or contact the maintainer.

---

**Note**: This is a scaffold implementation with placeholder data. Replace simulated API calls with actual service integrations for production use.
