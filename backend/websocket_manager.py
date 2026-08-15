#!/usr/bin/env python3
"""WebSocket handler for real-time JAKAL updates"""
from fastapi import WebSocket
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

class WebSocketManager:
    """Manage WebSocket connections and broadcasting"""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")
        
        # Send welcome message
        await self.broadcast({
            "event": "CONNECTION",
            "message": "Connected to JAKAL backend",
            "timestamp": datetime.utcnow().isoformat(),
            "level": "success"
        })
    
    def disconnect(self, websocket: WebSocket):
        """Handle client disconnect"""
        self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message: {str(e)}")
    
    async def broadcast_agent_event(self, agent_type: str, event: str, details: dict = None):
        """Broadcast an agent event"""
        message = {
            "event": f"AGENT_{event.upper()}",
            "agent_type": agent_type,
            "message": f"{agent_type} - {event}",
            "timestamp": datetime.utcnow().isoformat(),
            "level": "info",
            "details": details or {}
        }
        await self.broadcast(message)
    
    async def broadcast_scan_update(self, target: str, status: str, findings: int = 0):
        """Broadcast scan progress update"""
        message = {
            "event": "SCAN_UPDATE",
            "target": target,
            "status": status,
            "findings": findings,
            "timestamp": datetime.utcnow().isoformat(),
            "level": "info" if status == "in_progress" else "success"
        }
        await self.broadcast(message)
    
    async def broadcast_llm_event(self, action: str, result: str = None):
        """Broadcast LLM reasoning event"""
        message = {
            "event": "LLM_EVENT",
            "action": action,
            "message": f"LLM {action}",
            "result": result,
            "timestamp": datetime.utcnow().isoformat(),
            "level": "success"
        }
        await self.broadcast(message)
    
    async def broadcast_quantum_event(self, job_id: str, status: str):
        """Broadcast quantum job event"""
        message = {
            "event": "QUANTUM_EVENT",
            "job_id": job_id,
            "status": status,
            "message": f"Quantum job {status}",
            "timestamp": datetime.utcnow().isoformat(),
            "level": "info"
        }
        await self.broadcast(message)

# Global manager instance
ws_manager = WebSocketManager()
