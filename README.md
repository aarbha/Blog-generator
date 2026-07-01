# Blog Generator

Agentic blog writer using a hybrid Groq + Ollama pipeline. Routes knowledge-intensive tasks (research, analysis, writing) to Groq's free Llama 3.1 8B API and lightweight local models (qwen2.5:1.5b) for critique and polish. Runs under 2GB RAM CPU-only.

## Features

- Multi-agent pipeline: Scout, Analyst, Architect, Writer, Editor, Polisher
- Groq free tier integration for heavy lifting (128K context, zero GPU needed)
- Local fallback for light tasks (qwen2.5:1.5b, ~1GB RAM)
- RSS feed discovery + DuckDuckGo + 4 alternative news sources
- Long-form chapter support for comprehensive articles
- Self-critique and polish with structured scoring
- HTML preview with "Copy to Medium" button (pastes cleanly into Medium's editor)

## Quick Start

```bash
pip install -r requirements.txt
```

Set up your `.env` file (copy from `.env.example`):

```
GROQ_API_KEY=your_groq_api_key
```

Ollama models (pull at least the cheap one):

```bash
ollama pull qwen2.5:1.5b
ollama pull qwen2.5:3b   # for editor
```

Run:

```bash
python main.py
```

## Architecture

| Phase | Agent | Model | Task |
|---|---|---|---|
| Research | Scout | Llama 3.1 8B (Groq) | Query planning, web search |
| Analysis | Analyst | Llama 3.1 8B (Groq) | Content categorization |
| Outline | Architect | Llama 3.1 8B (Groq) | Section planning |
| Writing | Writer | Llama 3.1 8B (Groq) | Draft sections |
| Critique | Editor | qwen2.5:3b | Review & score |
| Polish | Polisher | qwen2.5:1.5b | Final formatting |

## Options

- `--local-only` — run entirely on Ollama (no Groq calls)
- `--depth auto|short|medium|long|comprehensive` — control article length

## Requirements

- Python 3.10+
- Ollama with at least qwen2.5:1.5b pulled
- Groq API key (free at console.groq.com)
- Works CPU-only on 8GB RAM systems
