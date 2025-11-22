# GWEN - Multi-Agent Cloud Status Monitor

**G**lobal **W**atch **E**ngine for **N**etwork services - A modern Python CLI tool for monitoring cloud service status across multiple providers.

## Installation (Modern Way - No .bat files!)

```bash
# Clone the repository
git clone https://github.com/marcodepumper/gwen-cli.git
cd gwen-cli

# Install as a proper Python package
pip install -e .
```

That's it! Now you have:
- ✅ `gwen` command available everywhere
- ✅ `gwen-server` command for the backend  
- ✅ Works on Windows, Linux, macOS
- ✅ No .bat files needed!

## Quick Start

**Step 1:** Start the backend server (in one terminal):
```bash
gwen-server
```

**Step 2:** Use the CLI (in another terminal):
```bash
gwen status
gwen incidents
gwen maintenance CloudflareAgent
gwen help
```

## What Senior Devs Get

This is now a proper Python package with:
- 📦 `pyproject.toml` (modern Python packaging)
- 🎯 Entry points via `console_scripts`
- 🏗️ Proper `src/` layout
- 📚 Single source of dependencies
- 🔧 Development mode with `pip install -e .`

No more:
- ❌ `.bat` wrappers
- ❌ `python script.py` commands
- ❌ Path management headaches
- ❌ Platform-specific scripts

## Commands

All commands work the same on Windows, Linux, and macOS:

```bash
gwen status                    # Show all services
gwen status CloudflareAgent    # Detailed view
gwen incidents --show-recent   # View incidents
gwen maintenance              # Upcoming maintenance
gwen list-agents              # List all agents
gwen help                     # Show help
```

## Features

- 🌍 **Multi-Provider**: Cloudflare, AWS, Azure, GCP, GitHub, Datadog, Atlassian
- 📊 **Component-Level Tracking**: See individual datacenter/region status
- 🗺️ **Regional Grouping**: Maintenance windows organized by geography
- 🎨 **Beautiful CLI**: Rich-formatted terminal output
- ⚡ **Fast**: Async concurrent agent execution

## Architecture

```
src/gwen_cli/
├── cli.py          → gwen command
├── server.py       → gwen-server command  
└── backend/        → FastAPI application
    ├── agents/     → 7 monitoring agents
    ├── orchestrator/
    └── common/
```

## Development

```bash
# Install in development mode
pip install -e .

# Make changes to code
# ... edit files ...

# Changes are immediately available
gwen status  # Uses your latest code!
```

## Troubleshooting

**Command not found?**
```bash
# Make sure pip bin directory is in PATH
pip install -e . --force-reinstall
```

**Backend not running?**
```bash
gwen-server  # Start the backend
```

**Check health:**
```bash
curl http://localhost:8000/health
```

## What Changed from Old Version

### Before (the "cringe" way 😅):
```cmd
cd D:\github\gwen-cli
.\gwen.bat status              # Windows only
python gwen.py status          # Cross-platform
```

### After (modern Python):
```bash
gwen status                    # Works everywhere!
```

### Technical Improvements:
1. **Proper packaging** with `pyproject.toml`
2. **Console scripts** instead of wrapper scripts
3. **src/ layout** (modern Python best practice)
4. **Single install** command
5. **Virtual environment** friendly
6. **Cross-platform** by default

## Requirements

- Python 3.9+
- All dependencies installed automatically via pip

## License

MIT
