# API Development & Protocol Engineering Skill

## Purpose
Use this skill when designing RESTful APIs, Server-Sent Events (SSE) streaming connections, WebSocket handlers, or backend integration endpoints.

## 1. Core Directives
1. **Clean Semantic Path Conventions**: Always design clean API resource endpoints. Use nouns for paths and standard HTTP verbs (GET, POST, PUT, DELETE) to represent mutations.
2. **Standard Payload Structures**: Every API response must use a consistent JSON format containing `status`, `data`, and `error` or `message` envelopes.
3. **Graceful Error Handling**: Never leak raw database stack traces. Catch exceptions and return standard HTTP error codes (400, 401, 403, 404, 500) with descriptive messages.
4. **SSE (Server-Sent Events) Streaming**: Implement streaming endpoints with proper `text/event-stream` headers, keeping connection loops synchronous and yields formatted as `data: {payload}\n\n`.

## 2. API Structural Architecture
Organize API endpoints cleanly by routers and schemas:
```
├── api/
│   ├── routers/
│   │   ├── auth.py          # Authentication handlers
│   │   ├── chat.py          # Chat completions and SSE streaming
│   │   └── workspaces.py    # Sandbox file management APIs
│   ├── schemas/
│   │   ├── request.py       # Pydantic schemas validating client inputs
│   │   └── response.py      # Standard envelopes for API output
│   └── main.py              # App instantiation and middleware binding
```

## 3. High-Quality Code Examples

### FastAPI RESTful Endpoint with SSE Streaming
```python
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import json, asyncio

router = APIRouter()

async def event_generator():
    for count in range(1, 6):
        await asyncio.sleep(0.5)
        # Yield SSE formatted data
        yield f"data: {json.dumps({'step': count, 'progress': 'Working...'})}\n\n"
    yield "data: [DONE]\n\n"

@router.get("/api/stream")
def get_stream():
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )
```

### Express Node.js Server-Sent Events (SSE) Handler
```javascript
app.get('/api/stream', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  
  let count = 0;
  const interval = setInterval(() => {
    count++;
    res.write(`data: ${JSON.stringify({ step: count })}\n\n`);
    if (count >= 5) {
      clearInterval(interval);
      res.write('data: [DONE]\n\n');
      res.end();
    }
  }, 500);
});
```

### WebSocket Handler in FastAPI
```python
from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Receive client text
            data = await websocket.receive_text()
            payload = json.loads(data)
            # Process and reply
            await websocket.send_text(json.dumps({
                "echo": payload.get("message"),
                "status": "success"
            }))
    except WebSocketDisconnect:
        print("Client disconnected.")
```
