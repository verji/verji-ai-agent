# Tiltfile for Verji AI Agent
# Local Kubernetes development with hot reload

# Load environment variables
load('ext://dotenv', 'dotenv')
dotenv()

# Configuration
config.define_string_list('to-run', args=True)
cfg = config.parse()

# Service groups
groups = {
    'infra': ['redis'],
    'backend': ['verji-vagent-graph', 'verji-vagent-bot'],
    'all': ['redis', 'verji-vagent-graph', 'verji-vagent-bot']
}

# Determine which services to run
services = cfg.get('to-run', ['all'])
if 'all' in services:
    services = groups['all']
else:
    expanded = []
    for svc in services:
        expanded.extend(groups.get(svc, [svc]))
    services = expanded

# Create namespace
k8s_namespace = 'verji-dev'

#──────────────────────────────────────────────────────────
# 1. REDIS (Infrastructure)
#──────────────────────────────────────────────────────────

if 'redis' in services:
    k8s_yaml('''
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: verji-dev
spec:
  ports:
    - port: 6379
      targetPort: 6379
  selector:
    app: redis
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: verji-dev
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
        command: ["redis-server", "--appendonly", "yes"]
        volumeMounts:
        - name: redis-data
          mountPath: /data
      volumes:
      - name: redis-data
        emptyDir: {}
''')

    k8s_resource('redis',
        port_forwards='6379:6379',
        labels=['infra'],
    )

#──────────────────────────────────────────────────────────
# 2. VERJI VAGENT GRAPH (Python LangGraph Service)
#──────────────────────────────────────────────────────────

if 'verji-vagent-graph' in services:
    # Build Docker image with live_update for hot reload
    docker_build(
        'verji-vagent-graph',
        context='./verji-vagent-graph',
        dockerfile='./verji-vagent-graph/Dockerfile.dev',
        live_update=[
            # Sync Python source files
            sync('./verji-vagent-graph/src', '/app/src'),

            # Python picks up changes automatically with watchfiles
            run('echo "Code synced - Python will auto-reload"'),
        ],
    )

    k8s_yaml('''
apiVersion: v1
kind: ConfigMap
metadata:
  name: verji-vagent-graph-config
  namespace: verji-dev
data:
  REDIS_URL: "redis://redis:6379"
  GRPC_PORT: "50051"
  LOG_LEVEL: "debug"
---
apiVersion: v1
kind: Service
metadata:
  name: verji-vagent-graph
  namespace: verji-dev
spec:
  ports:
    - port: 50051
      targetPort: 50051
      name: grpc
  selector:
    app: verji-vagent-graph
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: verji-vagent-graph
  namespace: verji-dev
spec:
  replicas: 1
  selector:
    matchLabels:
      app: verji-vagent-graph
  template:
    metadata:
      labels:
        app: verji-vagent-graph
    spec:
      containers:
      - name: verji-vagent-graph
        image: verji-vagent-graph
        ports:
        - containerPort: 50051
        envFrom:
        - configMapRef:
            name: verji-vagent-graph-config
        env:
        - name: OPENAI_API_KEY
          value: "''' + os.getenv('OPENAI_API_KEY', 'sk-test') + '''"
        - name: ANTHROPIC_API_KEY
          value: "''' + os.getenv('ANTHROPIC_API_KEY', '') + '''"
''')

    k8s_resource('verji-vagent-graph',
        port_forwards='50051:50051',
        labels=['backend'],
        resource_deps=['redis'],
        auto_init=True,
        trigger_mode=TRIGGER_MODE_AUTO,
    )

#──────────────────────────────────────────────────────────
# 3. VERJI VAGENT BOT (Rust Matrix Client)
#──────────────────────────────────────────────────────────

if 'verji-vagent-bot' in services:
    # Custom build for Rust with incremental compilation
    docker_build(
        'verji-vagent-bot',
        context='./verji-vagent-bot',
        dockerfile='./verji-vagent-bot/Dockerfile.dev',
        live_update=[
            sync('./verji-vagent-bot/src', '/app/src'),

            # Incremental recompile (faster than full rebuild)
            run('cd /app && cargo build --release',
                trigger=['./verji-vagent-bot/src']),

            # Restart the binary
            restart_container(),
        ],
    )

    k8s_yaml('''
apiVersion: v1
kind: ConfigMap
metadata:
  name: verji-vagent-bot-config
  namespace: verji-dev
data:
  REDIS_URL: "redis://redis:6379"
  GRPC_ENDPOINT: "http://verji-vagent-graph:50051"
  RUST_LOG: "debug,matrix_sdk=info"
---
apiVersion: v1
kind: Service
metadata:
  name: verji-vagent-bot
  namespace: verji-dev
spec:
  ports:
    - port: 8080
      targetPort: 8080
      name: metrics
  selector:
    app: verji-vagent-bot
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: verji-vagent-bot
  namespace: verji-dev
spec:
  replicas: 1
  selector:
    matchLabels:
      app: verji-vagent-bot
  template:
    metadata:
      labels:
        app: verji-vagent-bot
    spec:
      containers:
      - name: verji-vagent-bot
        image: verji-vagent-bot
        envFrom:
        - configMapRef:
            name: verji-vagent-bot-config
        env:
        - name: MATRIX_HOMESERVER
          value: "''' + os.getenv('MATRIX_HOMESERVER', 'https://matrix-client.matrix.org') + '''"
        - name: MATRIX_USER
          value: "''' + os.getenv('MATRIX_USER', '@bot:matrix.org') + '''"
        - name: MATRIX_PASSWORD
          value: "''' + os.getenv('MATRIX_PASSWORD', 'changeme') + '''"
        - name: ADMIN_ROOM_ID
          value: "''' + os.getenv('ADMIN_ROOM_ID', '!adminroom:matrix.org') + '''"
''')

    k8s_resource('verji-vagent-bot',
        port_forwards='8080:8080',
        labels=['backend'],
        resource_deps=['redis', 'verji-vagent-graph'],
        auto_init=True,
        trigger_mode=TRIGGER_MODE_AUTO,
    )

#──────────────────────────────────────────────────────────
# MANUAL TRIGGERS & TOOLS
#──────────────────────────────────────────────────────────

# Regenerate protocol buffers
local_resource(
    'proto-compile',
    cmd='./scripts/gen-proto.sh',
    deps=['./proto/chatbot.proto'],
    labels=['tools'],
    auto_init=False,  # Manual trigger
)

# Run integration tests
local_resource(
    'integration-tests',
    cmd='./scripts/test-integration.sh',
    resource_deps=['redis', 'verji-vagent-graph', 'verji-vagent-bot'],
    labels=['tests'],
    auto_init=False,  # Manual trigger
)

# Flush Redis cache
local_resource(
    'redis-flush',
    cmd='kubectl exec -n verji-dev deploy/redis -- redis-cli FLUSHALL',
    resource_deps=['redis'],
    labels=['tools'],
    auto_init=False,  # Manual trigger
)

print("""
╔════════════════════════════════════════════════════════════╗
║              Verji AI Agent - Tilt Dev Environment        ║
╚════════════════════════════════════════════════════════════╝

Services starting:
""" + '\n'.join(['  • ' + s for s in services]) + """

Tilt UI: http://localhost:10350

Port forwards:
  • Redis:              localhost:6379
  • verji-vagent-graph: localhost:50051 (gRPC)
  • verji-vagent-bot:   localhost:8080 (metrics)

Manual triggers:
  • proto-compile:      Regenerate protobuf code
  • integration-tests:  Run test suite
  • redis-flush:        Clear Redis cache

Hot reload enabled:
  • Python: < 1 sec (auto-reload with watchfiles)
  • Rust:   ~15 sec (incremental compilation)
""")
