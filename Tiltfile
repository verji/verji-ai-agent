# Tiltfile for Verji AI Agent
# Local Kubernetes development with hot reload

# Load Tilt extensions
load('ext://dotenv', 'dotenv')
load('ext://restart_process', 'docker_build_with_restart')

# Try to load .env, fall back to .env.example if not found
if os.path.exists('.env'):
    dotenv()
elif os.path.exists('.env.example'):
    dotenv('.env.example')
else:
    print("Warning: No .env or .env.example found, using hardcoded defaults")

# Configuration
config.define_string_list('to-run', args=True)
cfg = config.parse()

# Service groups
groups = {
    'infra': ['postgres', 'redis', 'synapse'],
    'frontend': ['verji-element-app'],
    'backend': ['verji-vagent-graph', 'verji-vagent-bot'],
    'all': ['postgres', 'redis', 'synapse', 'verji-element-app', 'verji-vagent-graph', 'verji-vagent-bot']
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
k8s_namespace = 'verji-ai-agent'

# Ensure namespace exists
k8s_yaml(blob('''
apiVersion: v1
kind: Namespace
metadata:
  name: verji-ai-agent
'''))

#──────────────────────────────────────────────────────────
# 1. POSTGRES (Infrastructure)
#──────────────────────────────────────────────────────────

if 'postgres' in services:
    k8s_yaml(blob('''
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: verji-ai-agent
spec:
  ports:
    - port: 5432
      targetPort: 5432
  selector:
    app: postgres
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  namespace: verji-ai-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:14
        ports:
        - containerPort: 5432
        env:
        - name: POSTGRES_DB
          value: synapse
        - name: POSTGRES_USER
          value: synapse
        - name: POSTGRES_PASSWORD
          value: synapsepwd
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        volumeMounts:
        - name: postgres-data
          mountPath: /var/lib/postgresql/data
      volumes:
      - name: postgres-data
        emptyDir: {}
'''))

    k8s_resource('postgres',
        port_forwards='5432:5432',
        labels=['infra'],
    )

#──────────────────────────────────────────────────────────
# 2. REDIS (Infrastructure)
#──────────────────────────────────────────────────────────

if 'redis' in services:
    k8s_yaml(blob('''
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: verji-ai-agent
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
  namespace: verji-ai-agent
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
        command: ["redis-server", "--requirepass", "redispwd", "--appendonly", "yes"]
        volumeMounts:
        - name: redis-data
          mountPath: /data
      volumes:
      - name: redis-data
        emptyDir: {}
'''))

    k8s_resource('redis',
        port_forwards='6379:6379',
        labels=['infra'],
    )

#──────────────────────────────────────────────────────────
# 3. SYNAPSE (Matrix Homeserver)
#──────────────────────────────────────────────────────────

if 'synapse' in services:
    k8s_yaml(blob('''
apiVersion: v1
kind: Service
metadata:
  name: synapse-svc
  namespace: verji-ai-agent
  labels:
    app.kubernetes.io/name: synapse-main
    component: synapse
spec:
  selector:
    app.kubernetes.io/name: synapse-main
  type: ClusterIP
  ports:
  - port: 8008
    name: http
    targetPort: 8008
    protocol: TCP
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  labels:
    app.kubernetes.io/component: synapse
    app.kubernetes.io/name: synapse-main
  name: synapse-main
  namespace: verji-ai-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: synapse-main
  serviceName: synapse-main
  template:
    metadata:
      labels:
        app.kubernetes.io/component: synapse
        app.kubernetes.io/name: synapse-main
    spec:
      containers:
      - image: matrixdotorg/synapse:latest
        imagePullPolicy: IfNotPresent
        name: synapse-main
        ports:
        - containerPort: 8008
          name: synapse-http
          protocol: TCP
        env:
        - name: SYNAPSE_SERVER_NAME
          value: "''' + os.getenv('SYNAPSE_SERVER_NAME', 'localhost') + '''"
        - name: SYNAPSE_REPORT_STATS
          value: "no"
        resources:
          limits:
            cpu: "1"
            memory: 1200Mi
          requests:
            cpu: 150m
            memory: 600Mi
        volumeMounts:
        - mountPath: /data
          name: synapse-data
      volumes:
      - name: synapse-data
        emptyDir: {}
  updateStrategy:
    type: RollingUpdate
'''))

    k8s_resource('synapse-main',
        port_forwards='8008:8008',
        labels=['infra'],
        resource_deps=['postgres'],
    )

#──────────────────────────────────────────────────────────
# 4. VERJI ELEMENT APP (Matrix Frontend)
#──────────────────────────────────────────────────────────

if 'verji-element-app' in services:
    k8s_yaml(blob('''
apiVersion: v1
kind: Service
metadata:
  name: verji-element-app-svc
  namespace: verji-ai-agent
  labels:
    app.kubernetes.io/name: verji-element-app
    component: verji-element-app
spec:
  type: ClusterIP
  selector:
    run: verji-element-app-deployment
  ports:
  - name: http
    port: 80
    targetPort: 80
    protocol: TCP
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: verji-element-app
  namespace: verji-ai-agent
  labels:
    component: verji-element-app
spec:
  replicas: 1
  selector:
    matchLabels:
      run: verji-element-app-deployment
  strategy:
    type: RollingUpdate
  template:
    metadata:
      labels:
        run: verji-element-app-deployment
    spec:
      containers:
      - name: verji-element-app
        image: vectorim/element-web:latest
        imagePullPolicy: IfNotPresent
        resources:
          requests:
            memory: "512Mi"
            cpu: "200m"
          limits:
            memory: "1000Mi"
            cpu: "400m"
        ports:
        - name: http
          containerPort: 80
          protocol: TCP
'''))

    k8s_resource('verji-element-app',
        port_forwards='8080:80',
        labels=['frontend'],
        resource_deps=['synapse-main'],
    )

#──────────────────────────────────────────────────────────
# 5. VERJI VAGENT GRAPH (Python LangGraph Service)
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

    k8s_yaml(blob('''
apiVersion: v1
kind: ConfigMap
metadata:
  name: verji-vagent-graph-config
  namespace: verji-ai-agent
data:
  REDIS_URL: "redis://:redispwd@redis:6379"
  GRPC_PORT: "50051"
  LOG_LEVEL: "debug"
---
apiVersion: v1
kind: Service
metadata:
  name: verji-vagent-graph
  namespace: verji-ai-agent
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
  namespace: verji-ai-agent
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
'''))

    k8s_resource('verji-vagent-graph',
        port_forwards='50051:50051',
        labels=['backend'],
        resource_deps=['redis'],
        auto_init=True,
        trigger_mode=TRIGGER_MODE_AUTO,
    )

#──────────────────────────────────────────────────────────
# 6. VERJI VAGENT BOT (Rust Matrix Client)
#──────────────────────────────────────────────────────────

if 'verji-vagent-bot' in services:
    # Custom build for Rust with incremental compilation and process restart
    docker_build_with_restart(
        'verji-vagent-bot',
        context='./verji-vagent-bot',
        dockerfile='./verji-vagent-bot/Dockerfile.dev',
        entrypoint=['/app/target/release/verji-vagent-bot'],
        live_update=[
            sync('./verji-vagent-bot/src', '/app/src'),

            # Incremental recompile (faster than full rebuild)
            run('cd /app && cargo build --release',
                trigger=['./verji-vagent-bot/src']),
        ],
    )

    k8s_yaml(blob('''
apiVersion: v1
kind: ConfigMap
metadata:
  name: verji-vagent-bot-config
  namespace: verji-ai-agent
data:
  REDIS_URL: "redis://:redispwd@redis:6379"
  GRPC_ENDPOINT: "http://verji-vagent-graph:50051"
  RUST_LOG: "debug,matrix_sdk=info"
---
apiVersion: v1
kind: Service
metadata:
  name: verji-vagent-bot
  namespace: verji-ai-agent
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
  namespace: verji-ai-agent
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
'''))

    k8s_resource('verji-vagent-bot',
        port_forwards='8081:8080',
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
    cmd='kubectl exec -n verji-ai-agent deploy/redis -- redis-cli -a redispwd FLUSHALL',
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
  • Postgres:           localhost:5432 (user: synapse, pass: synapsepwd)
  • Redis:              localhost:6379 (pass: redispwd)
  • Synapse:            localhost:8008 (Matrix homeserver)
  • Element Web:        localhost:8080 (Matrix client UI)
  • verji-vagent-graph: localhost:50051 (gRPC)
  • verji-vagent-bot:   localhost:8081 (metrics)

Manual triggers:
  • proto-compile:      Regenerate protobuf code
  • integration-tests:  Run test suite
  • redis-flush:        Clear Redis cache

Hot reload enabled:
  • Python: < 1 sec (auto-reload with watchfiles)
  • Rust:   ~15 sec (incremental compilation)

Matrix setup:
  1. Access Synapse at http://localhost:8008
  2. Access Element Web at http://localhost:8080
  3. Configure bot credentials in .env file
""")
