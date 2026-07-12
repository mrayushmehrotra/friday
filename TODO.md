make the jarvis-config webpage UI to add and remove commands from the jarvis,
and jarvis will include or exclude them based on the user's preferences

make the update todo command to in mcp, which can be used to input new text in the todo
e.g. add in todo, create the design.md website whcih takes github repo and extracts all css from it then give you a design.md file => so it'll add this in the todo

1. Replace raw HTTP \_query_llm() with ChatOllama from langchain-ollama. This would give you message templating, output parsers, streaming support, and callbacks without any HTTP boilerplate.
2. Replace the if/elif chain with LangChain's intent classifier -- either via LLMChain with a structured output schema, or LangGraph for routing.
3. Use StringOutputParser or PydanticOutputParser in the autonomous mode's generate_plan() -- currently it manually does find("[") + json.loads(), which is brittle.
4. Standardize all LLM calls -- currently \_query_llm and \_ollama_chat use different endpoints, different options, and different model env var conventions. LangChain would unify this.
5. Leverage LangSmith for observability/tracing across all LLM calls.

--- Daily Work ---

```markdown
# 6-Month AI Software Engineer Roadmap

> Goal: Become an interview-ready Full Stack + AI Engineer.

---

# Daily Checklist

## DSA (60 min)

- [ ] Solve 1-2 LeetCode problems
- [ ] Write solution without AI
- [ ] Optimize solution
- [ ] Review yesterday's problems

---

## Computer Science (60 min)

Rotate one topic every day.

- [ ] Operating Systems
- [ ] Networking
- [ ] Database Internals
- [ ] System Design

---

## AI Learning (90 min)

- [ ] Watch course/video
- [ ] Take notes
- [ ] Build a small demo
- [ ] Read documentation

---

## Project Development (2 Hours)

- [ ] Build one feature
- [ ] Write tests
- [ ] Refactor code
- [ ] Push to GitHub

---

## AI-Free Coding (30 min)

- [ ] Build something without AI assistance
- [ ] Ask AI only after finishing your first attempt

---

## Reading (30 min)

- [ ] Documentation
- [ ] Blog
- [ ] Engineering article

---

# Month 1 — Engineering Foundations

## Week 1

### JavaScript / TypeScript

- [ ] Event Loop
- [ ] Closures
- [ ] Execution Context
- [ ] Prototype Chain
- [ ] Async/Await
- [ ] Promises
- [ ] Generators
- [ ] Iterators

### Python

- [ ] Modern Syntax
- [ ] Type Hints
- [ ] Dataclasses
- [ ] Virtual Environments
- [ ] Pydantic

### DSA

- [ ] Arrays
- [ ] Strings

---

## Week 2

### Node.js

- [ ] Streams
- [ ] Buffers
- [ ] EventEmitter
- [ ] Worker Threads
- [ ] Child Processes

### Python

- [ ] Asyncio
- [ ] FastAPI Basics

### DSA

- [ ] Hash Maps
- [ ] Sliding Window
- [ ] Two Pointers

---

## Week 3

### Backend

- [ ] REST APIs
- [ ] Authentication
- [ ] JWT
- [ ] Validation
- [ ] Error Handling

### Python

- [ ] FastAPI CRUD

### DSA

- [ ] Linked List
- [ ] Stack
- [ ] Queue

---

## Week 4

### Project

- [ ] Build REST API
- [ ] Authentication
- [ ] Database
- [ ] Documentation
- [ ] Testing

---

# Month 2 — Backend Mastery

## PostgreSQL

- [ ] Indexes
- [ ] Joins
- [ ] Transactions
- [ ] Query Optimization
- [ ] Window Functions

## Redis

- [ ] Caching
- [ ] Pub/Sub
- [ ] Rate Limiting

## MongoDB

- [ ] Aggregation
- [ ] Indexes

## Backend

- [ ] File Upload
- [ ] Background Jobs
- [ ] WebSockets

## DSA

- [ ] Trees
- [ ] BST
- [ ] Heap
- [ ] Graph Basics

---

# Month 3 — AI Fundamentals

## Watch

- [ ] Neural Networks: Zero to Hero
- [ ] Let's Build GPT
- [ ] Intro to LLMs

## Learn

- [ ] Tokens
- [ ] Embeddings
- [ ] Transformers
- [ ] Attention
- [ ] Context Window
- [ ] Prompt Engineering
- [ ] Function Calling
- [ ] Structured Outputs

## Project

- [ ] AI Chatbot

---

# Month 4 — AI Engineering

## Learn

- [ ] RAG
- [ ] Vector Databases
- [ ] Chunking
- [ ] Retrieval
- [ ] LangGraph
- [ ] MCP
- [ ] AI Agents
- [ ] Memory
- [ ] Evaluation

## Projects

- [ ] Chat with PDFs
- [ ] AI Customer Support
- [ ] AI Research Assistant

---

# Month 5 — Production AI

## Learn

- [ ] Docker
- [ ] CI/CD
- [ ] Logging
- [ ] Monitoring
- [ ] Streaming
- [ ] Background Workers
- [ ] Deployment

## Projects

- [ ] AI Meeting Summarizer
- [ ] AI Code Reviewer
- [ ] Browser Agent

---

# Month 6 — Interview Preparation

## DSA

- [ ] Trees
- [ ] Graphs
- [ ] Dynamic Programming
- [ ] Backtracking

## System Design

- [ ] URL Shortener
- [ ] Chat App
- [ ] Notification Service
- [ ] AI SaaS Design

## Networking

- [ ] HTTP
- [ ] TCP/IP
- [ ] DNS
- [ ] Load Balancer
- [ ] Reverse Proxy

## Operating Systems

- [ ] Processes
- [ ] Threads
- [ ] Memory
- [ ] Scheduling

## Final Project

- [ ] Next.js Frontend
- [ ] Node Backend
- [ ] FastAPI AI Service
- [ ] PostgreSQL
- [ ] Redis
- [ ] Docker
- [ ] LangGraph
- [ ] MCP
- [ ] RAG
- [ ] Authentication
- [ ] Deployment

---

# Weekly Review

- [ ] 10+ LeetCode problems solved
- [ ] 5 GitHub commits
- [ ] 1 blog/article read
- [ ] 1 project feature completed
- [ ] Notes updated
- [ ] Resume updated (if needed)

---

# Monthly Goals

## Month 1

- [ ] Strong TypeScript
- [ ] Strong Node.js
- [ ] Modern Python
- [ ] FastAPI Basics

## Month 2

- [ ] Backend Ready
- [ ] PostgreSQL
- [ ] Redis
- [ ] Authentication

## Month 3

- [ ] Understand LLMs
- [ ] Build AI Chatbot

## Month 4

- [ ] Build RAG Applications
- [ ] Learn LangGraph
- [ ] Learn MCP

## Month 5

- [ ] Deploy Production AI Apps
- [ ] Docker + CI/CD

## Month 6

- [ ] Interview Ready
- [ ] Portfolio Complete
- [ ] Apply to Companies
```
