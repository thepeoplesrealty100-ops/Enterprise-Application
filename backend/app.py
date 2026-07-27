from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import os
from typing import Dict

app = FastAPI(title="JAKAL Backend")

# Allow origins - for dev we'll allow localhost and all (restrict in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500", "http://localhost:8000", "*"] ,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory telemetry queue (for demo)
telemetry_queue = asyncio.Queue()

async def produce_telemetry(message: Dict):
    await telemetry_queue.put(message)

@app.post("/api/v1/agents/action")
async def agent_action(payload: Dict):
    action = payload.get("action")
    target = payload.get("target")
    if not action:
        raise HTTPException(status_code=400, detail="Missing action")
    # Enqueue or execute agent action here (spawn background task)
    asyncio.create_task(produce_telemetry({"timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                                          "message": f"Agent action received: {action} target={target}",
                                          "level_color": "text-emerald-400"}))
    # Return a short acknowledgment
    return JSONResponse({"status": "enqueued", "action": action, "target": target})

@app.post("/api/v1/quantum/simulate")
async def quantum_simulate(payload: Dict):
    algorithm = payload.get("algorithm", "bell_state")
    shots = int(payload.get("shots", 1024))
    try:
        # Try to run qiskit Aer if available
        from qiskit import QuantumCircuit, execute, Aer
        if algorithm == "bell_state":
            qc = QuantumCircuit(2, 2)
            qc.h(0)
            qc.cx(0,1)
            qc.measure([0,1],[0,1])
            backend = Aer.get_backend('aer_simulator')
            job = execute(qc, backend=backend, shots=shots)
            result = job.result().get_counts()
        else:
            result = {"info": f"Algorithm {algorithm} not implemented in demo"}
    except Exception as exc:
        # fallback mocked result
        result = {"counts": {"00": shots // 2, "11": shots // 2}, "note": str(exc)}

    asyncio.create_task(produce_telemetry({"timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                                          "message": f"Quantum simulation {algorithm} finished",
                                          "level_color": "text-primary-color"}))
    return JSONResponse({"status": "ok", "result": result})

# Server-Sent Events endpoint for telemetry
async def telemetry_generator():
    while True:
        msg = await telemetry_queue.get()
        payload = json.dumps(msg)
        yield f"data: {payload}\n\n"

@app.get("/api/v1/telemetry/stream")
async def telemetry_stream():
    return StreamingResponse(telemetry_generator(), media_type="text/event-stream")
