# J.A.R.V.I.S - Local Llama Terminal Assistant

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

A JARVIS-like AI agent that uses local Llama AI to understand natural language commands, determine if they're terminal commands, and execute them safely.

## Features

- **Natural Language Interface** - Talk to JARVIS in plain English
- **Local Llama AI** - Runs entirely on your machine using Ollama
- **Command Classification** - Automatically detects terminal vs conversational commands
- **Safety First** - Configurable safety levels with dangerous command protection
- **Rich CLI** - Beautiful terminal interface with colored output
- **Configurable** - Fully customizable via config file

## Quick Start

### Prerequisites

- Python 3.8+
- [Ollama](https://ollama.ai/) installed
- A Llama model (e.g., `llama3.2`)

### Installation

1. Install Ollama and pull a model:
```bash
brew install ollama          # macOS
curl -fsSL https://ollama.com/install.sh | sh  # Linux

ollama pull llama3.2
```

2. Clone the repository:
```bash
git clone https://github.com/yourusername/jarvis.git
cd jarvis
```

3. Create virtual environment and install dependencies:
```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

4. Run JARVIS:
```bash
python -m jarvis.cli
```

## Usage Examples

```
You: list files in current directory
JARVIS: I'll run ls -la for you...
       Executing: ls -la
       [output of ls command]

You: what time is it?
JARVIS: The current time is 2:34 PM.

You: show me the weather
JARVIS: I can't check the weather, but I can help with terminal commands!
```

## Project Structure

```
jarvis/
├── jarvis/
│   ├── __init__.py
│   ├── cli.py          # Command line interface
│   ├── core.py         # Main agent logic
│   ├── llm.py          # LLM integration
│   ├── terminal.py     # Terminal command handling
│   └── config.py       # Configuration
├── tests/
├── requirements.txt
└── README.md
```

## Configuration

Create a `.jarvisrc` file or use `config.yaml`:

```yaml
llm:
  endpoint: "http://localhost:11434"
  model: "llama3.2"

safety:
  level: "cautious"  # paranoid, cautious, permissive

terminal:
  timeout: 30
  default_dir: "~"
```

### Safety Levels

| Level | Description |
|-------|-------------|
| `paranoid` | Blocks all modifications |
| `cautious` | Confirms destructive commands (default) |
| `permissive` | Executes most commands |

## Development

Run tests:
```bash
pytest tests/
```

## Contributing

Pull requests are welcome! Please read the contribution guidelines first.

## License

MIT License - see [LICENSE](LICENSE) for details.
