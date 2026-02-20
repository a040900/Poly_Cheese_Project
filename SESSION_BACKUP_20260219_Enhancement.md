
# Session Backup: Internal AI Engine Integration

## Objective
The goal was to implement an internal AI Engine that allows the backend to directly call OpenAI APIs (or compatible) for system analysis, replacing the need for an external agent script running on a VPS. This provides centralized management, API Key security, and controllable monitoring frequency via the Web UI.

## Implementation Details

### 1. Configuration (`backend/app/config.py`)
- Added `AI_MONITOR_ENABLED` (default: False)
- Added `AI_MONITOR_INTERVAL` (default: 900s / 15min)
- Added `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` settings.
- These settings can be overridden by environment variables or via the API.

### 2. Internal AI Engine (`backend/app/llm/engine.py`)
- Created `AIEngine` class (Component) that runs a background task loop.
- Periodically (every 15 min) builds a context snapshot using `prompt_builder`.
- Calls OpenAI Chat Completion API with the context and system prompt.
- Feeds the response JSON into `llm_advisor.process_advice()` to execute mode switching or risk management actions.
- Handles errors and logging robustly.

### 3. Backend Integration (`backend/app/main.py`)
- Integrated `ai_engine` into the `lifespan` startup/shutdown sequence.
- Added REST API endpoints:
    - `GET /api/settings/ai`: Retrieve current AI settings and status (API Key masked).
    - `POST /api/settings/ai`: Update settings and restart the AI Engine dynamically.

### 4. Frontend UI (`frontend/index.html`, `frontend/js/app.js`)
- Added an **"AI Settings" button** to the navbar.
- Implemented a configuration Modal with fields for:
    - Enable/Disable Toggle
    - API Key (Password field)
    - Base URL & Model Name
    - Monitoring Interval
- Added JavaScript logic to fetch/save settings and display real-time engine status.
- Added visual feedback (Toasts) for setting updates.

## User Instructions
1.  **Restart the Backend**: The new changes require a backend restart to load the new modules.
2.  **Open Web UI**: Click the "🤖 AI Settings" button in the top navigation bar.
3.  **Configure**:
    - Check "Enable AI Monitor".
    - Enter your OpenAI API Key (or DeepSeek/Claude compatible key).
    - Set Base URL (e.g., `https://api.openai.com/v1`).
    - Click "Save & Restart AI".
4.  **Verification**: You should see a "✅ AI 監控已啟動" toast message. The system will now automatically analyze market conditions every 15 minutes.

## Files Modified
- `backend/app/config.py`
- `backend/app/main.py`
- `backend/app/llm/engine.py` (New)
- `frontend/index.html`
- `frontend/js/app.js`

## Notes
- The external AI Agent script is no longer strictly necessary if this internal engine is enabled.
- Both can coexist, but verify that they don't issue conflicting mode switches simultaneously.
