# JAKAL Kubernetes Deployment & Claude Integration Guide

## PART 1: LOCAL TESTING & DEPLOYMENT

### Step 1: Build Docker Image Locally

```bash
# Build the image
docker build -t jakal:v2.5 .

# Verify it built successfully
docker images | grep jakal
```

### Step 2: Test Container Locally

```bash
# Run the container
docker run -d -p 8000:8000 --name jakal-test jakal:v2.5

# Wait for startup
sleep 10

# Test health endpoint
curl http://localhost:8000/health

# Test API docs
curl http://localhost:8000/api/docs

# View logs
docker logs jakal-test

# Stop container
docker stop jakal-test
docker rm jakal-test
```

### Step 3: Push to Container Registry

**For AWS ECR:**
```bash
# Get login token
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 123456789.dkr.ecr.us-east-1.amazonaws.com

# Tag and push
docker tag jakal:v2.5 123456789.dkr.ecr.us-east-1.amazonaws.com/jakal:v2.5
docker push 123456789.dkr.ecr.us-east-1.amazonaws.com/jakal:v2.5
```

**For GCP GCR:**
```bash
# Configure Docker
gcloud auth configure-docker

# Tag and push
docker tag jakal:v2.5 gcr.io/your-project/jakal:v2.5
docker push gcr.io/your-project/jakal:v2.5
```

**For Docker Hub:**
```bash
# Login
docker login

# Tag and push
docker tag jakal:v2.5 your-username/jakal:v2.5
docker push your-username/jakal:v2.5
```

---

## PART 2: KUBERNETES DEPLOYMENT

### Step 1: Create Kubernetes Manifests

**File: k8s/jakal-deployment.yaml**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jakal-backend
  namespace: default
spec:
  replicas: 3
  selector:
    matchLabels:
      app: jakal
  template:
    metadata:
      labels:
        app: jakal
    spec:
      containers:
      - name: jakal
        image: your-registry/jakal:v2.5  # Update this
        ports:
        - containerPort: 8000
          name: http
        env:
        - name: PYTHONUNBUFFERED
          value: "1"
        - name: API_HOST
          value: "0.0.0.0"
        - name: API_PORT
          value: "8000"
        - name: DUCKDB_PATH
          value: "/data/jakal.duckdb"
        - name: FRONTEND_DIR
          value: "/app/frontend"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /api/health
            port: 8000
          initialDelaySeconds: 20
          periodSeconds: 5
          timeoutSeconds: 3
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        volumeMounts:
        - name: data
          mountPath: /data
        - name: logs
          mountPath: /app/logs
      volumes:
      - name: data
        emptyDir: {}
      - name: logs
        emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: jakal-service
  namespace: default
spec:
  selector:
    app: jakal
  ports:
  - port: 80
    targetPort: 8000
    protocol: TCP
    name: http
  type: LoadBalancer
```

### Step 2: Deploy to Kubernetes

```bash
# Create namespace (optional)
kubectl create namespace jakal
kubectl set-context --current --namespace=jakal

# Apply deployment
kubectl apply -f k8s/jakal-deployment.yaml

# Check deployment status
kubectl get deployment jakal-backend
kubectl get pods -l app=jakal
kubectl get svc jakal-service

# Watch rollout
kubectl rollout status deployment/jakal-backend

# Get service IP
kubectl get svc jakal-service
# Access at: http://<EXTERNAL-IP>

# View logs
kubectl logs -f deployment/jakal-backend
kubectl logs -f pods/jakal-backend-<POD-ID>

# Scale replicas
kubectl scale deployment jakal-backend --replicas=5

# Update image (rolling update)
kubectl set image deployment/jakal-backend jakal=your-registry/jakal:v2.6
kubectl rollout status deployment/jakal-backend
```

### Step 3: Verify Kubernetes Deployment

```bash
# Check health
kubectl exec -it <POD-NAME> -- curl http://localhost:8000/health

# Port forward to local machine
kubectl port-forward svc/jakal-service 8000:80
# Access at: http://localhost:8000

# Test API
curl http://localhost:8000/api/health
curl http://localhost:8000/api/docs

# Check resource usage
kubectl top pods -l app=jakal
kubectl describe pod <POD-NAME>

# View events
kubectl get events
kubectl describe deployment jakal-backend
```

---

## PART 3: CLAUDE AI INTEGRATION GUIDE

### How to Add Claude as a Collaborative AI Partner

Claude is an advanced AI model by Anthropic. Here are several ways to integrate Claude into your development workflow:

### Option 1: Using Claude via API (Recommended for Team)

**Install Claude SDK:**
```bash
pip install anthropic
```

**Create `backend/claude_integration.py`:**

```python
from anthropic import Anthropic

class ClaudeAssistant:
    def __init__(self, api_key: str = None):
        self.client = Anthropic(api_key=api_key)  # Uses ANTHROPIC_API_KEY env var
        self.conversation_history = []

    async def chat(self, message: str) -> str:
        """Send message to Claude and get response."""
        self.conversation_history.append({
            "role": "user",
            "content": message
        })

        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",  # or claude-3-opus-20240229
            max_tokens=2048,
            system="""You are an expert software engineer helping with JAKAL Enterprise Application development.
You understand:
- FastAPI architecture
- DuckDB databases
- Kubernetes deployments
- Security operations
- Quantum computing integration
- Post-quantum cryptography

Provide clear, actionable code solutions.""",
            messages=self.conversation_history
        )

        assistant_message = response.content[0].text
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })

        return assistant_message

    def clear_history(self):
        """Reset conversation."""
        self.conversation_history = []
```

**Add to FastAPI (`backend/app.py`):**

```python
from claude_integration import ClaudeAssistant

claude = ClaudeAssistant()

@app.post("/api/claude/ask")
async def ask_claude(payload: dict):
    """Ask Claude for development assistance."""
    question = payload.get("question", "")
    response = await claude.chat(question)
    return {"question": question, "response": response}

@app.post("/api/claude/clear")
async def clear_claude_context():
    """Clear Claude conversation history."""
    claude.clear_history()
    return {"status": "cleared"}
```

### Option 2: Direct API Integration

**Set environment variable:**
```bash
export ANTHROPIC_API_KEY="sk-ant-xxxxxxxxxxxxx"  # Get from Claude API dashboard
```

**Get API key from:** https://console.anthropic.com/

### Option 3: Use Claude in Development (Local)

**Install Claude CLI tool:**
```bash
pip install anthropic-cli
```

**Test Claude directly:**
```bash
anthropic -api-key $ANTHROPIC_API_KEY "Explain JAKAL's architecture"
```

### Option 4: Claude Desktop Integration (For Daily Development)

1. **Download Claude Desktop** from https://claude.ai/download
2. **Install MCP Plugin** for development
3. **Configure in Claude settings**:
   ```json
   {
     "claude": {
       "tools": [
         {
           "name": "jakal-dev",
           "type": "api",
           "url": "http://localhost:8000/api"
         }
       ]
     }
   }
   ```

---

## PART 4: TEAM COLLABORATION WITH CLAUDE

### Workflow 1: Code Review with Claude

```bash
# 1. Ask Claude to review code
curl -X POST http://localhost:8000/api/claude/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Review this FastAPI router for security issues: [paste code]"
  }'

# 2. Get improvements suggested
# 3. Implement suggestions
# 4. Ask Claude to verify
```

### Workflow 2: Feature Development

```
1. You: "Claude, help me add a new security agent for X"
2. Claude: Provides implementation plan
3. You: Ask Claude for code skeleton
4. Claude: Generates code
5. You: Implement and test
6. Claude: Reviews and suggests optimizations
7. Done!
```

### Workflow 3: Troubleshooting

```
1. Issue occurs in Kubernetes
2. You: Send error logs to Claude
3. Claude: Analyzes and suggests fixes
4. You: Apply fixes
5. Claude: Verifies solution
```

---

## PART 5: DOCKER COMPOSE WITH CLAUDE API

**Create `docker-compose.yml` with Claude service:**

```yaml
version: '3.8'

services:
  jakal-backend:
    build: .
    image: jakal:v2.5
    container_name: jakal-backend
    ports:
      - "8000:8000"
    environment:
      - PYTHONUNBUFFERED=1
      - API_HOST=0.0.0.0
      - API_PORT=8000
      - DUCKDB_PATH=/data/jakal.duckdb
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}  # Pass from .env
    volumes:
      - ./data:/data
      - ./logs:/app/logs
    depends_on:
      - ollama
    networks:
      - jakal-net

  ollama:
    image: ollama/ollama:latest
    container_name: jakal-ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama-models:/root/.ollama
    networks:
      - jakal-net

volumes:
  ollama-models:

networks:
  jakal-net:
    driver: bridge
```

**.env file:**

```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx
OLLAMA_MODEL=llama3
```

**Run with Claude:**

```bash
# Set API key
export ANTHROPIC_API_KEY="sk-ant-xxxxxxxxxxxxx"

# Start stack
docker-compose up -d

# Test Claude endpoint
curl -X POST http://localhost:8000/api/claude/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the key features of JAKAL?"}'
```

---

## PART 6: SETUP CHECKLIST

### Local Development
- [ ] Docker installed
- [ ] ANTHROPIC_API_KEY set
- [ ] docker-compose working
- [ ] Container running
- [ ] Health endpoint working
- [ ] Claude API responding

### Kubernetes Deployment
- [ ] kubectl installed
- [ ] Registry credentials configured
- [ ] Image pushed to registry
- [ ] K8s manifests updated
- [ ] Deployment applied
- [ ] Service accessible
- [ ] Pods running healthy

### Claude Integration
- [ ] API key obtained
- [ ] SDK installed (pip install anthropic)
- [ ] Integration code added
- [ ] Endpoint tested
- [ ] Team access configured

---

## PART 7: EXAMPLE: USING CLAUDE FOR OPTIMIZATION

### Ask Claude to Optimize Performance

```python
async def ask_claude_optimization():
    question = """
    Our JAKAL API has 50+ endpoints. 
    Average response time is 500ms. 
    How can we optimize?
    We use: FastAPI, DuckDB, async/await
    """
    
    response = await claude.chat(question)
    print(response)
    # Claude might suggest:
    # - Database indexing
    # - Query optimization
    # - Caching strategies
    # - Async improvements
    # - Connection pooling
```

---

## PART 8: PRODUCTION CONSIDERATIONS

### Security
- ✅ Never commit ANTHROPIC_API_KEY
- ✅ Use secrets manager (AWS Secrets, K8s Secrets)
- ✅ Rate limit Claude API calls
- ✅ Audit Claude interactions

### Cost
- Anthropic charges per token
- Cache frequently asked questions
- Set usage limits in console

### Monitoring
```python
@app.get("/api/claude/stats")
async def claude_stats():
    return {
        "conversations": len(claude.conversation_history),
        "tokens_used": "TBD",
        "cost_estimate": "TBD"
    }
```

---

## QUICK REFERENCE COMMANDS

```bash
# Docker
docker build -t jakal:v2.5 .
docker run -p 8000:8000 jakal:v2.5

# Kubernetes
kubectl apply -f k8s/jakal-deployment.yaml
kubectl get pods
kubectl logs -f deployment/jakal-backend
kubectl port-forward svc/jakal-service 8000:80

# Claude API
export ANTHROPIC_API_KEY="sk-ant-xxxxxxxxxxxxx"
curl -X POST http://localhost:8000/api/claude/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Your question here"}'

# Testing
curl http://localhost:8000/health
curl http://localhost:8000/api/docs
```

---

**Status: READY FOR DEPLOYMENT & CLAUDE INTEGRATION** ✅🚀

Next: Deploy to Kubernetes cluster and start using Claude for collaborative development!
