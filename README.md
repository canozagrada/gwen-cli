# GWEN - Multi-Agent Cloud Status Monitor

**G**lobal **W**atch **E**ngine for **N**etwork services - A Python CLI tool for monitoring cloud service status across multiple providers.

## Overview

GWEN monitors operational status of major cloud providers including Cloudflare, AWS, Azure, GCP, GitHub, Datadog, and Atlassian. It aggregates status information, incidents, and scheduled maintenance into a unified command-line interface.

### Key Features

- 🌍 **Multi-Provider Monitoring**: Track 7 major cloud services simultaneously
- 📊 **Component-Level Tracking**: Monitor individual datacenter and region status
- 🗺️ **Regional Grouping**: Maintenance windows organized by geography
- 📅 **Incident History**: Access up to 14 days of incident data
- 🎨 **Beautiful CLI**: Rich-formatted terminal output
- ⚡ **Fast Performance**: Async concurrent agent execution
- 🔧 **Modern Architecture**: Proper Python package with entry points

## Installation

```bash
# Clone the repository
git clone https://github.com/marcodepumper/gwen-cli.git
cd gwen-cli

# Install the package
pip install -e .
```

This installs:
- `gwen` - CLI command (works globally on Windows, Linux, macOS)
- `gwen-server` - Backend server command

## Quick Start

**1. Start the backend server:**
```bash
gwen-server
```

**2. Use the CLI:**
```bash
gwen status                    # Show all services
gwen status CloudflareAgent    # Detailed service view
gwen incidents --show-recent   # View incidents
gwen maintenance              # Upcoming maintenance
gwen help                     # Command reference
```

## Commands

### `gwen status [agent]`
Display current operational status of all services or a specific service.

```bash
gwen status                    # Summary table of all services
gwen status CloudflareAgent    # Detailed view with component breakdown
```

**Output includes:**
- Service health status (Operational, Degraded, Outage)
- Component-level issues (e.g., specific datacenters)
- Active incident counts
- Scheduled maintenance counts
- Last update timestamp

### `gwen incidents [options]`
View ongoing and historical incidents.

```bash
gwen incidents                      # Show ongoing incidents only
gwen incidents --show-recent        # Include resolved incidents (last 14 days)
gwen incidents --days 7             # Last 7 days of history
gwen incidents CloudflareAgent      # Specific service only
```

**Options:**
- `--show-recent` - Include resolved incidents
- `--days N` - Number of days to look back (default: 14)

### `gwen maintenance [agent]`
Display scheduled maintenance windows with regional grouping.

```bash
gwen maintenance                   # All services
gwen maintenance CloudflareAgent   # Specific service with regional breakdown
```

**Features:**
- Sorted by date (soonest first)
- In-progress maintenance highlighted
- Regional grouping (North America, Europe, Asia, etc.)
- Compact location codes (DFW, LAX, SIN, LHR)

### `gwen list-agents`
List all available monitoring agents.

```bash
gwen list-agents
```

### `gwen help`
Display detailed command reference and usage examples.

```bash
gwen help
```

## Architecture

GWEN is built as a modern Python package with proper structure:

```
gwen-cli/
├── pyproject.toml              # Project configuration and dependencies
└── src/
    └── gwen_cli/               # Main package
        ├── cli.py              # CLI entry point (gwen command)
        ├── server.py           # Server entry point (gwen-server command)
        └── backend/            # FastAPI application
            ├── main.py         # API server
            ├── agents/         # 7 monitoring agents
            │   ├── cloudflare.py
            │   ├── aws.py
            │   ├── azure.py
            │   ├── gcp.py
            │   ├── github.py
            │   ├── datadog.py
            │   └── atlassian.py
            ├── orchestrator/   # Agent coordination
            └── common/         # Shared utilities
```

**Components:**
- **CLI** - Rich-formatted command-line interface using `gwen` command
- **Backend** - FastAPI server with async agent orchestration
- **Agents** - Specialized monitoring agents for each cloud provider

### API Endpoints

The backend server exposes REST endpoints at `http://localhost:8000`:

- `GET /` - System information
- `GET /health` - Health check
- `POST /retrieve-status` - Execute all agents and get status
- `GET /agent-status` - Get all agent statuses  
- `GET /agents` - List available agents
- `POST /agents/{agent_name}/execute` - Execute specific agent

## Development

### Setting Up Development Environment

```bash
# Clone the repository
git clone https://github.com/marcodepumper/gwen-cli.git
cd gwen-cli

# Install in development mode
pip install -e .

# Make code changes
# ... edit files in src/gwen_cli/ ...

# Test changes immediately (no reinstall needed)
gwen status
```

### Adding a New Agent

1. Create a new agent class in `src/gwen_cli/backend/agents/your_agent.py`
2. Inherit from `BaseAgent` class
3. Implement the `_execute_task()` method
4. Register the agent in `src/gwen_cli/backend/orchestrator/orchestrator.py`

### Running Tests

```bash
# Start the backend for testing
gwen-server

# In another terminal, test commands
gwen status
gwen incidents --show-recent
gwen maintenance
```

## Troubleshooting

### Command not found after installation

Ensure pip's bin directory is in your PATH:

```bash
# Reinstall to verify
pip install -e . --force-reinstall

# Check installation
pip show gwen-cli
```

### Backend server not connecting

Start the backend server:
```bash
gwen-server
```

Verify it's running:
```bash
curl http://localhost:8000/health
```

### Port already in use

If port 8000 is occupied, you can modify the server configuration in `src/gwen_cli/server.py`.

## Requirements

- **Python**: 3.9 or higher
- **Dependencies**: Automatically installed via pip
  - FastAPI >= 0.100.0
  - uvicorn >= 0.23.0
  - rich >= 13.0.0
  - aiohttp >= 3.8.0
  - pydantic >= 2.0.0
  - And others (see `pyproject.toml`)

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - See LICENSE file for details

## Monitored Services

- **Cloudflare** - Global CDN and security services
- **AWS** - Amazon Web Services
- **Azure** - Microsoft cloud platform
- **GCP** - Google Cloud Platform
- **GitHub** - Development platform and services
- **Datadog** - Monitoring and analytics platform
- **Atlassian** - Jira, Confluence, and other services
