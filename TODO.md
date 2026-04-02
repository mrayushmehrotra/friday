# JARVIS AI Agent - Local Llama Terminal Assistant

## Project Overview
Build a JARVIS-like AI agent that uses local Llama AI to understand natural language commands, determine if they're terminal commands, and execute them safely.

---

## Phase 1: Project Setup

- [ ] Initialize Python project with virtual environment
- [ ] Create `requirements.txt` with dependencies
- [ ] Set up project structure:
  ```
  jarvis/
  ├── jarvis/
  │   ├── __init__.py
  │   ├── cli.py          # Command line interface
  │   ├── core.py         # Main agent logic
  │   ├── llm.py           # LLM integration
  │   ├── terminal.py     # Terminal command handling
  │   └── config.py       # Configuration
  ├── tests/
  ├── requirements.txt
  └── README.md
  ```
- [ ] Install dependencies (requests, rich, etc.)

---

## Phase 2: Llama Integration

- [ ] Research Llama setup options:
  - Ollama (recommended for ease)
  - llama.cpp
  - LM Studio
- [ ] Create LLM interface class
- [ ] Implement connection to local Llama API (Ollama default: `localhost:11434`)
- [ ] Add model selection configuration
- [ ] Handle LLM connection errors gracefully
- [ ] Test basic LLM communication

---

## Phase 3: Command Classification

- [ ] Design prompt template for command classification
- [ ] Implement `classify_command()` function:
  - Detect if input is a terminal command
  - Extract the actual command if yes
  - Handle non-terminal queries (conversation)
- [ ] Add confidence threshold for classification
- [ ] Implement fallback for ambiguous inputs

---

## Phase 4: Terminal Command Execution

- [ ] Create `execute_command()` function
- [ ] Implement command validation/safety checks
- [ ] Add timeout handling for long-running commands
- [ ] Capture stdout, stderr separately
- [ ] Return formatted execution results
- [ ] Implement working directory awareness

---

## Phase 5: Safety Features

- [ ] Implement dangerous command blacklist (rm -rf, format, etc.)
- [ ] Add warning prompts for risky commands
- [ ] Implement confirmation system for destructive commands
- [ ] Add user-configurable safety levels:
  - `paranoid`: Block all modifications
  - `cautious`: Confirm destructive commands
  - `permissive`: Execute most commands
- [ ] Log all executed commands with timestamps

---

## Phase 6: User Interface

- [ ] Create interactive CLI loop
- [ ] Add colored/formatted output using Rich
- [ ] Implement input history (arrow up/down)
- [ ] Add visual indicators for:
  - Thinking/processing state
  - Command execution status
  - Errors
- [ ] Create startup banner
- [ ] Add `--help` and `--version` flags
- [ ] Implement quit/exit commands

---

## Phase 7: Configuration System

- [ ] Create `config.yaml` or `.jarvisrc` file
- [ ] Configuration options:
  - LLM endpoint URL
  - Model name
  - Safety level
  - Default working directory
  - Command timeout
  - Theme/preferences
- [ ] Implement config loading and validation
- [ ] Add `--config` flag to specify config path

---

## Phase 8: Error Handling & Edge Cases

- [ ] Handle LLM unavailable/offline scenarios
- [ ] Handle malformed LLM responses
- [ ] Handle terminal command not found errors
- [ ] Handle permission denied errors
- [ ] Handle timeout scenarios
- [ ] Implement retry logic for transient failures
- [ ] Add detailed error messages

---

## Phase 9: Testing

- [ ] Write unit tests for command classification
- [ ] Write unit tests for terminal execution
- [ ] Write unit tests for safety checks
- [ ] Add integration tests for LLM flow
- [ ] Test edge cases (empty input, special characters, etc.)
- [ ] Test offline functionality

---

## Phase 10: Documentation & Polish

- [ ] Write comprehensive README.md
- [ ] Document installation steps for Ollama
- [ ] Add examples of usage
- [ ] Document configuration options
- [ ] Add troubleshooting section
- [ ] Create setup script (optional)

---

## Phase 11: Future Enhancements (Optional)

- [ ] Add streaming responses from LLM
- [ ] Implement command history search
- [ ] Add alias system for common commands
- [ ] Implement context awareness (recent files, git status, etc.)
- [ ] Add support for multiple LLM backends
- [ ] Create web UI version
- [ ] Add voice input/output
- [ ] Implement multi-step command decomposition

---

## Quick Start Checklist

1. [ ] Install Ollama and pull a model (`ollama pull llama3.2`)
2. [ ] Clone/fork this repo
3. [ ] Create virtual environment
4. [ ] Install dependencies
5. [ ] Configure settings
6. [ ] Run `python -m jarvis.cli`
7. [ ] Ask: "list files in current directory"
8. [ ] Ask: "show me the weather" (should respond conversationally)
