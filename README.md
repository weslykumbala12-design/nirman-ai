# NIRMAN AI

**Graph-Guided, Feedback-Driven Generation of Traversable 3D Buildings from Real-World Photographs**

> Final-year CSE project · Python 3.11+ · Blender 4.x · React · MongoDB

---

## Architecture

```
Photos + Prompts
      │
      ▼
┌─────────────────────┐
│  Graph Context Mgr  │  ← Cells, typed edges, BFS subgraph retrieval
│   (Module 2)        │    Measures token reduction vs. full-context
└────────┬────────────┘
         │ selected cells + failure history
         ▼
┌─────────────────────┐
│   VLM Planner       │  ← Gemini 2.0 Flash / GPT-4o
│   (Module 3)        │    Generates structured JSON BuildingSpec
└────────┬────────────┘
         │ JSON spec
         ▼
┌─────────────────────┐
│  Spec Validator     │  ← Schema + BFS connectivity + geometry checks
│   (Module 4)        │    Requests VLM correction if invalid
└────────┬────────────┘
         │ validated spec
         ▼
┌─────────────────────┐
│  Geometry Kernel    │  ← Segment-based walls (no Boolean ops)
│  + Code Generator   │    Open doorways, stairs, stairwell holes, roof
│   (Module 5)        │
└────────┬────────────┘
         │ Blender Python script
         ▼
┌─────────────────────┐
│  Blender Execution  │  ← Headless subprocess or Docker sandbox
│   (Module 6)        │    Exports GLTF + .blend
└────────┬────────────┘
         │ ExecutionResult
         ▼
┌─────────────────────┐
│  Verification       │  ← Execution · BFS traversability · Doorway clearance
│   Engine            │    Staircase accessibility · Visual fidelity · Mesh
│   (Module 7)        │    Returns VerificationReport with scores + suggestions
└────────┬────────────┘
         │ VerificationReport
         ▼
┌─────────────────────┐
│  Failure Memory     │  ← MongoDB: attempts, scores, failure_categories
│  + Selection        │    Best-of-N selector · ε-greedy strategy bandit
│   (Module 8/9)      │
└────────┬────────────┘
         │ best candidate
         ▼
┌─────────────────────┐
│   Web Interface     │  ← React + Three.js · Upload · Generate · View · Feedback
│   (Module 10)       │    FastAPI backend
└─────────────────────┘
```

---

## Setup

### 1 — Clone and install Python dependencies

```bash
git clone <your-repo-url> nirman_ai
cd nirman_ai
pip install -e ".[dev]"
```

### 2 — Configure environment

```bash
cp .env.example .env
# Edit .env and set:
#   GEMINI_API_KEY=<your key>   (or OPENAI_API_KEY for GPT-4o)
#   VLM_PROVIDER=gemini
#   MONGODB_URI=mongodb://localhost:27017
#   BLENDER_EXECUTION_MODE=local
#   BLENDER_EXECUTABLE=C:\Program Files\Blender Foundation\Blender 4.2\blender.exe
```

### 3 — Start MongoDB

```bash
# Docker (recommended)
docker run -d -p 27017:27017 --name nirman-mongo mongo:7

# Or use a local MongoDB installation
```

### 4 — Build the Docker image for Blender (optional, for sandboxed mode)

```bash
docker build -t nirman-blender:latest ./docker/
```

### 5 — Start the backend API

```bash
uvicorn nirman.api.main:app --reload --port 8000
```

### 6 — Start the frontend

```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

---

## API Quick Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/buildings/{id}/upload-photos` | Upload photos + prompts |
| `POST` | `/api/v1/buildings/{id}/generate` | Run generation pipeline |
| `GET`  | `/api/v1/buildings/{id}/attempts` | List all attempts |
| `GET`  | `/api/v1/buildings/{id}/attempts/{aid}` | Get single attempt |
| `POST` | `/api/v1/buildings/{id}/attempts/{aid}/feedback` | Accept / Reject |
| `GET`  | `/api/v1/buildings/{id}/attempts/{aid}/gltf` | Download GLTF |
| `POST` | `/api/v1/buildings/{id}/rooms/{rid}/edit` | Targeted room edit |
| `GET`  | `/api/v1/buildings/{id}/graph` | Get photo-cell graph |
| `GET`  | `/api/v1/buildings/{id}/failure-patterns` | Failure pattern summary |
| `GET`  | `/api/v1/bandit/stats` | Strategy bandit statistics |

### Example: Generate a building

```bash
# 1. Upload photos
curl -X POST http://localhost:8000/api/v1/buildings/b001/upload-photos \
  -F "files=@front.jpg" -F "prompts=front facade" -F "hints=exterior"

# 2. Generate
curl -X POST http://localhost:8000/api/v1/buildings/b001/generate \
  -H "Content-Type: application/json" \
  -d '{"user_request": "2-floor house, lobby, kitchen, 2 bedrooms, bathroom, flat roof"}'

# 3. Submit feedback
curl -X POST http://localhost:8000/api/v1/buildings/b001/attempts/<id>/feedback \
  -H "Content-Type: application/json" \
  -d '{"feedback": "looks good", "accepted": true}'
```

---

## Running Tests

```bash
pytest tests/ -v
```

All tests run without Blender or MongoDB (uses mocks and simulated data).

---

## Running Experiments (Item 9)

```bash
# Dry run — simulates all 5 ablation conditions
python -m experiments.run_experiments --dry_run --runs 10

# Analyse results
python -m experiments.analyse \
  --results experiments/results/results_<timestamp>.json \
  --latex
```

---

## Module Map

| Module | Path | Description |
|---|---|---|
| Config | `nirman/config.py` | Pydantic settings from `.env` |
| Graph | `nirman/graph/` | Photo cells, typed edges, BFS retrieval |
| VLM | `nirman/vlm/` | Gemini/OpenAI abstraction, prompt builder, planner |
| Validation | `nirman/validation/` | Pydantic schema + 3-layer validator |
| Kernel | `nirman/kernel/` | Blender geometry kernel + code generator |
| Execution | `nirman/execution/` | Local + Docker Blender runner |
| Verification | `nirman/verification/` | 6-check verification engine |
| Memory | `nirman/memory/` | MongoDB failure memory store |
| Selection | `nirman/selection/` | Best-of-N + ε-greedy bandit |
| Pipeline | `nirman/pipeline.py` | End-to-end orchestrator |
| API | `nirman/api/` | FastAPI routes + app |
| Frontend | `frontend/` | React + Three.js web interface |
| Experiments | `experiments/` | Ablation runner + analysis |
| Tests | `tests/` | Full test suite (no Blender/MongoDB required) |

---

## Tech Stack

| Component | Technology |
|---|---|
| VLM | Google Gemini 2.0 Flash / OpenAI GPT-4o |
| 3D Generation | Blender 4.x (headless Python API) |
| Schema Validation | Pydantic v2 |
| Graph Management | NetworkX |
| Failure Memory | MongoDB + Motor (async) |
| Backend API | FastAPI + Uvicorn |
| Frontend | React 18 + Vite |
| 3D Viewer | Three.js + React Three Fiber |
| Execution Sandbox | Docker (network disabled) |
| Tests | Pytest |
