#!/usr/bin/env python3
"""
CTPaS - Containerized Traffic Predictor as a Service
One-Touch Installation Script (XGBoost+SHAP / LSTM+SHAP)
Final version with all fixes:
- Deployment name env var
- LSTM epochs=12
- SHAP guard (>50 background)
- PVC ReadWriteMany
- LSTM data check
- Retrain every 30 cycles
"""

import os
import zipfile
import glob
import subprocess

# =============================================================================
# HELM CHART FILES
# =============================================================================

def write_chart_yaml():
    with open("Chart.yaml", "w") as f:
        f.write('''apiVersion: v2
name: ctpas
description: Containerized Traffic Predictor as a Service (XGBoost/LSTM + SHAP)
version: 1.0.0
appVersion: "1.0"
type: application
''')

def write_values_yaml():
    with open("values.yaml", "w") as f:
        f.write('''# Global values
global:
  imagePullPolicy: IfNotPresent
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000

persistence:
  enabled: true
  storageClassName: ""
  accessMode: ReadWriteMany          # Must be supported by your cluster
  size: 2Gi
  annotations: {}

server:
  replicas: 1
  image:
    repository: ctpas-server
    tag: latest
    pullPolicy: IfNotPresent
  service:
    type: NodePort
    port: 8080
    nodePort: 30007
  resources:
    requests:
      memory: "128Mi"
      cpu: "100m"
    limits:
      memory: "256Mi"
      cpu: "500m"

client:
  replicas: 1
  image:
    repository: ctpas-client
    tag: latest
    pullPolicy: IfNotPresent
  serverIp: ""
  serverPort: 30007
  sleepValue: 5
  stepValue: 1
  resources:
    requests:
      memory: "128Mi"
      cpu: "100m"
    limits:
      memory: "256Mi"
      cpu: "500m"

predictor:
  model: xgboost                # choose: xgboost or lstm
  image:
    repository: ctpas-predictor
    tag: latest
    pullPolicy: IfNotPresent
  scalingThreshold: 100
  frequencyMinutes: 1
  minNumRecords: 10
  scaleInThreshold: 0.6
  maxReplicas: 15
  retrainEveryCycles: 30         # retrain every 30 cycles (30 minutes)
  enableShap: true                # enable SHAP explanations
  resources:
    requests:
      memory: "1Gi"
      cpu: "500m"
    limits:
      memory: "2Gi"
      cpu: "2"
''')

def write_helpers():
    with open("templates/_helpers.tpl", "w") as f:
        f.write('''{{- define "ctpas.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "ctpas.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "ctpas.labels" -}}
helm.sh/chart: {{ include "ctpas.name" . }}
{{ include "ctpas.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "ctpas.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ctpas.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "ctpas.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "ctpas.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "ctpas.pvcName" -}}
{{- include "ctpas.fullname" . }}-storage
{{- end }}
''')

def write_storage():
    with open("templates/08-storage/persistentvolume.yaml", "w") as f:
        f.write('''{{- if and .Values.persistence.enabled (not .Values.persistence.existingClaim) }}
kind: PersistentVolume
apiVersion: v1
metadata:
  name: {{ include "ctpas.fullname" . }}-pv
  labels:
    {{- include "ctpas.labels" . | nindent 4 }}
spec:
  capacity:
    storage: {{ .Values.persistence.size }}
  accessModes:
    - {{ .Values.persistence.accessMode }}
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  hostPath:
    path: "/data/ctpas-shared"
    type: DirectoryOrCreate
{{- end }}
''')
    with open("templates/08-storage/persistentvolumeclaim.yaml", "w") as f:
        f.write('''{{- if .Values.persistence.enabled }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "ctpas.pvcName" . }}
  labels:
    {{- include "ctpas.labels" . | nindent 4 }}
  {{- with .Values.persistence.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  accessModes:
    - {{ .Values.persistence.accessMode }}
  resources:
    requests:
      storage: {{ .Values.persistence.size }}
  storageClassName: ""
{{- end }}
''')

def write_rbac():
    with open("templates/01-rbac/serviceaccount.yaml", "w") as f:
        f.write('''apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "ctpas.fullname" . }}-predictor
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "ctpas.labels" . | nindent 4 }}
''')
    with open("templates/01-rbac/role.yaml", "w") as f:
        f.write('''apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ include "ctpas.fullname" . }}-predictor-role
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "ctpas.labels" . | nindent 4 }}
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "watch", "update", "patch"]
- apiGroups: ["apps"]
  resources: ["deployments/scale"]
  verbs: ["get", "update", "patch"]
- apiGroups: [""]
  resources: ["pods", "services", "endpoints"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["persistentvolumeclaims"]
  verbs: ["get", "list", "watch"]
''')
    with open("templates/01-rbac/rolebinding.yaml", "w") as f:
        f.write('''apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ include "ctpas.fullname" . }}-predictor-binding
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "ctpas.labels" . | nindent 4 }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ include "ctpas.fullname" . }}-predictor-role
subjects:
- kind: ServiceAccount
  name: {{ include "ctpas.fullname" . }}-predictor
  namespace: {{ .Release.Namespace }}
''')

# =============================================================================
# COMBINED PREDICTOR SCRIPT (XGBoost+SHAP, LSTM+SHAP) with all fixes
# =============================================================================
PREDICTOR_PY = r'''#!/usr/bin/env python3
"""
CTPaS Predictor – Pluggable Model (XGBoost+SHAP or LSTM+SHAP)
"""

import os
import sys
import json
import time
import math
import subprocess
from datetime import datetime
from pathlib import Path
import warnings
warnings.filterwarnings("ignore", message="Saving into deprecated binary model format")
warnings.filterwarnings("ignore", message=".*tf.*")

import numpy as np
import pandas as pd



# ========== GLOBAL IMPORTS (deferred per model) ==========

# XGBoost
XGB_AVAILABLE = False
try:
    import xgboost as xgb
    xgb.set_config(verbosity=0)
    import shap
    from sklearn.metrics import r2_score
    from sklearn.preprocessing import StandardScaler
    import joblib
    XGB_AVAILABLE = True
except ImportError:
    xgb = shap = r2_score = StandardScaler = joblib = None

# LSTM (TensorFlow)
# Global to avoid TF retracing warning.
GLOBAL_LSTM_MODEL = None
GLOBAL_LSTM_SCALER = None
GLOBAL_LSTM_PREDICT_FN = None
LSTM_AVAILABLE = False
try:
    import tensorflow as tf
    from tensorflow.keras.models import Sequential, load_model
    from tensorflow.keras.layers import LSTM, Dense, Dropout
    from sklearn.preprocessing import MinMaxScaler
    import joblib as jl
    LSTM_AVAILABLE = True
except ImportError:
    tf = Sequential = load_model = LSTM = Dense = Dropout = MinMaxScaler = jl = None

# ========== CONFIGURATION ==========
DATA_PATH = os.getenv("DATA_PATH", "/data/ctpas-shared/server/server.csv")
SCALE_OUT_THRESHOLD = int(os.getenv("SCALING_THRESHOLD", "100"))
SCALE_IN_RATIO = float(os.getenv("SCALE_IN_THRESHOLD_RATIO", "0.4"))
MIN_RECORDS = int(os.getenv("MIN_NUM_RECORDS", "10"))
PREDICTOR_MODEL = os.getenv("PREDICTOR_MODEL", "xgboost").lower()
FREQUENCY_MINUTES = int(os.getenv("FREQUENCY_MINUTES", "1"))
MAX_REPLICAS = int(os.getenv("MAX_REPLICAS", "15"))
MIN_REPLICAS = 1
HYSTERESIS_UP = 1.15
HYSTERESIS_DOWN = 0.75
COOLDOWN_CYCLES = 3
RETRAIN_EVERY = int(os.getenv("RETRAIN_EVERY_N_CYCLES", "30"))  # 30 cycles
MAX_REPLICA_STEP = 2
ENABLE_SHAP = os.getenv("ENABLE_SHAP", "true").lower() == "true"
SERVER_DEPLOYMENT = os.getenv("SERVER_DEPLOYMENT_NAME", "ctpas-server")  # actual deployment name

# LSTM specific
LOOKBACK = 10
FORECAST = 5

# Model storage (separate subdirs)
MODEL_BASE = Path("/data/ctpas-shared/predictor/models")
MODEL_BASE.mkdir(parents=True, exist_ok=True)
XGB_MODEL_DIR = MODEL_BASE / "xgboost"
LSTM_MODEL_DIR = MODEL_BASE / "lstm"
XGB_MODEL_DIR.mkdir(exist_ok=True)
LSTM_MODEL_DIR.mkdir(exist_ok=True)

# Cooldown state (per model, in /tmp)
COOLDOWN_DIR = Path("/tmp/ctpas-cooldown")
COOLDOWN_DIR.mkdir(exist_ok=True)
COOLDOWN_FILE = COOLDOWN_DIR / f"last_scale_{PREDICTOR_MODEL}.json"
SCALE_OUT_COOLDOWN = 120   # seconds
SCALE_IN_COOLDOWN  = 300

# Retraining state (per model)
RETRAIN_FILE = COOLDOWN_DIR / f"last_train_cycle_{PREDICTOR_MODEL}.json"



# ========== LOGGING ==========
def log(msg):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

# ========== DATA LOADING (common) ==========
# ========== DATA LOADING (robust) ==========
def load_data():
    if not os.path.exists(DATA_PATH):
        log("⚠️ server.csv not found")
        return None, None
    try:
        df = pd.read_csv(DATA_PATH)
        # -----------------------------
        # Normalize columns
        # -----------------------------
        if "request_count" not in df.columns:
            if "count" in df.columns:
                df = df.rename(columns={"count": "request_count"})
            else:
                df = pd.read_csv(
                    DATA_PATH,
                    header=None,
                    names=["timestamp","request_count","message","response"]
                )
        if "client_message" in df.columns:
            df = df.rename(columns={"client_message":"message"})
        if "message" not in df.columns:
            df["message"] = ""
        # -----------------------------
        # Clean types
        # -----------------------------
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df["request_count"] = pd.to_numeric(df["request_count"], errors="coerce")
        df = df.dropna(subset=["timestamp","request_count"])
        # Remove bootstrap rows
        df = df[df["message"] != "SYNTHETIC_BOOTSTRAP"]
        df = df.sort_values("timestamp")
        if len(df) == 0:
            log("⚠️ No valid rows after cleaning")
            return None, None
        # -----------------------------
        # Compute RPM
        # -----------------------------
        rate = (
            df.set_index("timestamp")["request_count"]
              .resample("1min")
              .count()
              .fillna(0)
              .to_frame(name="rate")
              .reset_index()
        )
        log(f"Loaded {len(df)} raw requests")
        log(f"Generated {len(rate)} RPM samples")
        return df, rate
    except Exception as e:
        log(f"❌ Data load error: {e}")
        return None, None

# ========== COOLDOWN HELPERS ==========
def load_cooldown():
    if not COOLDOWN_FILE.exists():
        return {"last_scale_out": 0, "last_scale_in": 0}
    try:
        with open(COOLDOWN_FILE, "r") as f:
            return json.load(f)
    except:
        return {"last_scale_out": 0, "last_scale_in": 0}

def save_cooldown(state):
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(state, f)

def cooldown_active(action):
    state = load_cooldown()
    now = int(time.time())
    if action == "scale_out":
        remaining = SCALE_OUT_COOLDOWN - (now - state["last_scale_out"])
        return remaining > 0, max(remaining, 0)
    elif action == "scale_in":
        remaining = SCALE_IN_COOLDOWN - (now - state["last_scale_in"])
        return remaining > 0, max(remaining, 0)
    return False, 0

def update_cooldown(action):
    state = load_cooldown()
    now = int(time.time())
    if action == "scale_out":
        state["last_scale_out"] = now
    elif action == "scale_in":
        state["last_scale_in"] = now
    save_cooldown(state)

def should_retrain(cycle):
    """Check if retraining is needed based on cycle number."""
    if not RETRAIN_FILE.exists():
        # First run, always train
        with open(RETRAIN_FILE, "w") as f:
            json.dump({"last_cycle": cycle}, f)
        return True
    try:
        with open(RETRAIN_FILE, "r") as f:
            data = json.load(f)
        last = data.get("last_cycle", 0)
        if cycle - last >= RETRAIN_EVERY:
            data["last_cycle"] = cycle
            with open(RETRAIN_FILE, "w") as f:
                json.dump(data, f)
            return True
    except:
        pass
    return False

# ========== KUBERNETES HELPERS ==========
def get_current_replicas():
    try:
        out = subprocess.check_output(
            ["kubectl", "get", "deployment", SERVER_DEPLOYMENT, "-n", "ctpas",
             "-o", "jsonpath={.spec.replicas}"],
            universal_newlines=True
        )
        return int(out.strip())
    except:
        log("⚠️ Could not get current replicas, assuming 1")
        return 1

def kubectl_scale(replicas):
    try:
        subprocess.check_call(
            ["kubectl", "scale", "deployment", SERVER_DEPLOYMENT, "-n", "ctpas",
             f"--replicas={replicas}"])
        log(f"✅ Scaled server to {replicas} replicas")
    except Exception as e:
        log(f"❌ Scaling failed: {e}")

# ========== XGBOOST IMPLEMENTATION (with SHAP) ==========
# ========== XGBOOST IMPLEMENTATION (with SHAP) ==========
def run_xgboost(raw_data, data, cycle):
    import numpy as np
    import pandas as pd
    import shap
    import xgboost as xgb
    from pathlib import Path

    MODEL_PATH = XGB_MODEL_DIR / "model.json"
    MIN_TRAINING_SAMPLES = 20

    log("")
    log("======================================")
    log(f"🔄 Cycle {cycle} XGBoost with SHAP")
    log("======================================")
    log(f"COLUMNS = {list(data.columns)}")

    # ------------------------------------------------
    # RPM FIX (compute true RPM from last 60 seconds)
    # ------------------------------------------------
    if raw_data is not None and "timestamp" in raw_data.columns:
        df_rpm = raw_data.copy()
        df_rpm["timestamp"] = pd.to_datetime(df_rpm["timestamp"])
        now = df_rpm["timestamp"].max()
        window_start = now - pd.Timedelta(seconds=60)
        current_rate = float(len(df_rpm[df_rpm["timestamp"] >= window_start]))
    else:
        # Fallback if raw_data not available (e.g., early cycles)
        current_rate = float(data["rate"].iloc[-1])
        log(f"⚠️ Raw data unavailable – using resampled fallback: {current_rate:.1f} RPM")

    log(f"📊 Current RPM observed : {current_rate:.1f}")
    current_replicas = get_current_replicas()
    log(f"Current replicas: {current_replicas}")

    # -----------------------------
    # Feature Engineering
    # -----------------------------
    df = data.copy()

    df["lag_1"] = df["rate"].shift(1)
    df["lag_2"] = df["rate"].shift(2)
    df["lag_3"] = df["rate"].shift(3)

    df["diff_1"] = df["rate"] - df["lag_1"]
    df["diff_2"] = df["lag_1"] - df["lag_2"]

    df["roll_mean_5"] = df["rate"].rolling(5).mean()
    df["roll_std_5"] = df["rate"].rolling(5).std()

    df["trend_3"] = df["lag_1"] - df["lag_3"]

    df["target"] = df["rate"].shift(-1)

    df = df.dropna()

    if len(df) < MIN_TRAINING_SAMPLES:
        log(f"⚠️ Waiting for training history ({len(df)}/{MIN_TRAINING_SAMPLES})")
        return {
            "action": "none",
            "replicas": current_replicas,
            "reason": "Insufficient training history",
        }

    features = [
        "lag_1",
        "lag_2",
        "lag_3",
        "diff_1",
        "diff_2",
        "roll_mean_5",
        "roll_std_5",
        "trend_3",
    ]

    X = df[features]
    y = df["target"]

    log(f"Training samples available: {len(X)}")

    # -----------------------------
    # Model Load or Retrain
    # -----------------------------
    retrain = should_retrain(cycle) or not MODEL_PATH.exists()

    if retrain:
        log("🔄 Retraining XGBoost model...")

        model = xgb.XGBRegressor(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            objective="reg:squarederror",
            random_state=42,
            verbosity=0
        )

        model.fit(X, y)

        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        model.save_model(str(MODEL_PATH))

        log("✅ XGBoost model retrained and saved (JSON format)")

    else:
        model = xgb.XGBRegressor(verbosity=0)
        model.load_model(str(MODEL_PATH))
        log("✅ Loaded existing XGBoost model")

    # -----------------------------
    # Prediction
    # -----------------------------
    last_row = X.iloc[-1:]
    raw_prediction = float(model.predict(last_row)[0])

    # ────────────────────────────────────────────────
    # CHANGED: 50/50 smoothing for faster response to low traffic
    # ────────────────────────────────────────────────
    prediction = 0.5 * raw_prediction + 0.5 * current_rate

    log(f"📊 Current rate observed        : {current_rate:.1f} RPM")
    log(f"🔮 Predicted next-cycle load    : {prediction:.1f} RPM")
    delta = prediction - current_rate
    log(f"📈 Predicted change             : {delta:+.1f} RPM")
    log(f"Features used                   : {features}")

    # -----------------------------
    # Spike Guard (kept for safety)
    # -----------------------------
    if current_rate > 0 and prediction > current_rate * 3:
        log(
            f"⚠️ Sanity guard triggered – unrealistic spike prediction ({prediction:.1f} RPM)"
        )
        return {
            "action": "none",
            "replicas": current_replicas,
            "reason": f"Prediction anomaly ({prediction:.1f} RPM)",
        }

    # -----------------------------
    # SHAP Explanation
    # -----------------------------
    if ENABLE_SHAP:
        try:
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(last_row)

            if isinstance(shap_values, list):
                shap_values = shap_values[0]

            impact = list(zip(features, shap_values[0]))
            impact = sorted(impact, key=lambda x: abs(x[1]), reverse=True)[:4]

            log("🔍 Top drivers influencing prediction (XGBoost):")

            for name, val in impact:
                arrow = "↑" if val > 0 else "↓"
                log(f"   {arrow} {name:<12} ({val:+.2f})")

        except Exception as e:
            log(f"SHAP skipped: {e}")

    # ────────────────────────────────────────────────
    # CHANGED: Desired-replicas logic – scale purely based on prediction
    # ────────────────────────────────────────────────
    desired = int(np.ceil(prediction / SCALE_OUT_THRESHOLD))
    desired = max(MIN_REPLICAS, min(desired, MAX_REPLICAS))

    if desired > current_replicas:
        return {
            "action": "scale_out",
            "replicas": desired,
            "reason": f"XGBoost predicts higher load ({prediction:.0f} RPM)"
        }

    elif desired < current_replicas:
        return {
            "action": "scale_in",
            "replicas": desired,
            "reason": f"XGBoost predicts lower load ({prediction:.0f} RPM)"
        }

    else:
        return {
            "action": "none",
            "replicas": desired,
            "reason": "Load stable"
        }

# ========== LSTM IMPLEMENTATION (with SHAP) ==========
def run_lstm(raw_data, data, cycle):
    global GLOBAL_LSTM_MODEL
    global GLOBAL_LSTM_SCALER
    global GLOBAL_LSTM_PREDICT_FN

    if not LSTM_AVAILABLE:
        log("LSTM not available – falling back to no action")
        return {'action': 'none', 'replicas': get_current_replicas(), 'reason': 'LSTM unavailable'}

    SCALE_IN_THRESHOLD = SCALE_OUT_THRESHOLD * 0.4   # still defined for reference, but no longer used in decision

    MIN_SEQS = 10  # Min for viable training

    log("")
    log("======================================")
    log(f"🔄 Cycle {cycle} LSTM with SHAP")
    log("======================================")

    # ------------------------------------------------
    # RPM FIX (compute true RPM from last 60 seconds)
    # ------------------------------------------------
    if raw_data is not None and "timestamp" in raw_data.columns:
        df_rpm = raw_data.copy()
        df_rpm["timestamp"] = pd.to_datetime(df_rpm["timestamp"])
        now = df_rpm["timestamp"].max()
        window_start = now - pd.Timedelta(seconds=60)
        current_rate = float(len(df_rpm[df_rpm["timestamp"] >= window_start]))
    else:
        current_rate = float(data["rate"].iloc[-1])
        log(f"⚠️ Raw data unavailable – using resampled fallback: {current_rate:.1f} RPM")

    log(f"📊 Current RPM observed : {current_rate:.1f}")
    current_replicas = get_current_replicas()
    log(f"Current replicas: {current_replicas}")

    # ---------- Prepare data ----------
    try:
        values = data['rate'].values.reshape(-1, 1).astype(float)
    except Exception as e:
        log(f"⚠️ Failed reading rate column: {e}")
        return {'action': 'none', 'replicas': current_replicas, 'reason': 'Invalid dataset'}

    if len(values) < LOOKBACK + FORECAST:
        log(f"Not enough history for LSTM (need {LOOKBACK + FORECAST}, have {len(values)}) – waiting...")
        return {'action': 'none', 'replicas': current_replicas, 'reason': 'Not enough history for LSTM'}

    model_dir = LSTM_MODEL_DIR
    scaler_path = model_dir / "scaler.pkl"
    model_path = model_dir / "model.keras"

    # Seq count for guards
    num_possible_seqs = len(values) - LOOKBACK - FORECAST + 1
    force_retrain = (
        num_possible_seqs < 50
        and num_possible_seqs >= MIN_SEQS
        and cycle % 5 == 0
    )
    retrain = should_retrain(cycle) or force_retrain or not (model_path.exists() and scaler_path.exists())

    # ---------- TRAIN MODEL ----------
    if retrain:
        tf.keras.backend.clear_session()
        log(f"🔄 Training LSTM model (seqs: {num_possible_seqs})")

        scaler = MinMaxScaler(feature_range=(0, 1))

        try:
            scaled_data = scaler.fit_transform(values)
        except Exception as e:
            log(f"⚠️ Scaling failed: {e}")
            return {'action': 'none', 'replicas': current_replicas, 'reason': 'Scaling failed'}

        X, y = [], []
        for i in range(len(scaled_data) - LOOKBACK - FORECAST + 1):
            X.append(scaled_data[i:i + LOOKBACK])
            y.append(scaled_data[i + LOOKBACK:i + LOOKBACK + FORECAST, 0])

        X = np.array(X)
        y = np.array(y)

        if len(X) == 0 or len(y) == 0:
            log("⚠️ Skipping LSTM training – empty sequences")
            return {'action': 'none', 'replicas': current_replicas, 'reason': 'Empty training sequences'}

        if len(X) != len(y):
            log(f"⚠️ LSTM sequence mismatch: X={len(X)} y={len(y)}")
            return {'action': 'none', 'replicas': current_replicas, 'reason': 'Sequence mismatch'}

        if len(X) < MIN_SEQS:
            log(f"⚠️ Insufficient sequences for training ({len(X)}/{MIN_SEQS}) – waiting...")
            return {'action': 'none', 'replicas': current_replicas, 'reason': f'Not enough sequences ({len(X)} < {MIN_SEQS})'}

        model = Sequential([
            LSTM(32, return_sequences=True, input_shape=(LOOKBACK, 1)),
            Dropout(0.2),
            LSTM(32, return_sequences=False),
            Dropout(0.2),
            Dense(16, activation='relu'),
            Dense(FORECAST)
        ])

        model.compile(optimizer='adam', loss='mse')

        try:
            batch_size = min(16, len(X) // 4) if len(X) < 16 else 16
            verbose = 1 if num_possible_seqs < 50 else 0
            history = model.fit(X, y, epochs=12, batch_size=batch_size, verbose=0)
            log(f"Train loss: {history.history['loss'][-1]:.4f}")
        except Exception as e:
            log(f"⚠️ LSTM training failed: {e}")
            return {'action': 'none', 'replicas': current_replicas, 'reason': 'Training failed'}

        try:
            model.save(str(model_path))
            jl.dump(scaler, str(scaler_path))
            GLOBAL_LSTM_MODEL = model
            GLOBAL_LSTM_SCALER = scaler
            GLOBAL_LSTM_PREDICT_FN = tf.function(model.call, reduce_retracing=True)
            log("✅ LSTM model retrained, cached and saved")
        except Exception as e:
            log(f"⚠️ Failed saving model: {e}")

    # ---------- LOAD MODEL ----------
    else:
        try:
            if GLOBAL_LSTM_MODEL is None:
                GLOBAL_LSTM_MODEL = load_model(str(model_path))
                GLOBAL_LSTM_SCALER = jl.load(str(scaler_path))
                GLOBAL_LSTM_PREDICT_FN = tf.function(
                    GLOBAL_LSTM_MODEL.call,
                    reduce_retracing=True
                )
                log("✅ Loaded existing LSTM model (cached)")

            model = GLOBAL_LSTM_MODEL
            scaler = GLOBAL_LSTM_SCALER
            predict_fn = GLOBAL_LSTM_PREDICT_FN
            scaled_data = scaler.transform(values)
        except Exception as e:
            log(f"⚠️ Failed loading LSTM model: {e} – forcing retrain next cycle")
            return {'action': 'none', 'replicas': current_replicas, 'reason': 'Model load failure'}

    # ---------- Prepare prediction window ----------
    try:
        last_window = scaled_data[-LOOKBACK:].reshape(1, LOOKBACK, 1).astype(np.float32)
        last_window = tf.convert_to_tensor(last_window, dtype=tf.float32)
    except Exception as e:
        log(f"⚠️ Window creation failed: {e}")
        return {'action': 'none', 'replicas': current_replicas, 'reason': 'Window failure'}

    # ---------- Prediction ----------
    try:
        pred_scaled = GLOBAL_LSTM_PREDICT_FN(last_window, training=False).numpy()[0]
    except Exception as e:
        log(f"⚠️ LSTM prediction failed: {e}")
        return {'action': 'none', 'replicas': MIN_REPLICAS, 'reason': 'Prediction failure'}

    dummy = np.zeros((1, 1))
    predictions = []
    for i in range(FORECAST):
        dummy[0, 0] = pred_scaled[i]
        try:
            predictions.append(scaler.inverse_transform(dummy)[0, 0])
        except Exception:
            predictions.append(0)

    raw_avg_prediction = float(np.mean(predictions))
    # ────────────────────────────────────────────────
    # CHANGED: 50/50 smoothing for faster response to low traffic
    # ────────────────────────────────────────────────
    avg_prediction = 0.5 * raw_avg_prediction + 0.5 * current_rate
    avg_prediction = max(0, avg_prediction)

    # ---------- SHAP Explainability ----------
    if ENABLE_SHAP:
        try:
            background = scaled_data[:min(100, len(scaled_data) - LOOKBACK - FORECAST)]
            if len(background) >= LOOKBACK:
                background_sequences = np.array([
                    background[i:i + LOOKBACK].astype(np.float32)
                    for i in range(len(background) - LOOKBACK + 1)
                ], dtype=np.float32)

                if len(background_sequences) > 50:
                    input_window = last_window.numpy() if hasattr(last_window, "numpy") else np.array(last_window)
                    explainer = shap.GradientExplainer(model, background_sequences[:50])
                    shap_values_list = explainer.shap_values(input_window)

                    if isinstance(shap_values_list, list):
                        numpy_values = []
                        for v in shap_values_list:
                            if isinstance(v, tf.Tensor):
                                v = v.numpy()
                            v = np.array(v)
                            numpy_values.append(v)
                        shap_values = np.mean(np.stack(numpy_values, axis=0), axis=0)
                    else:
                        shap_values = shap_values_list
                        if isinstance(shap_values, tf.Tensor):
                            shap_values = shap_values.numpy()
                        shap_values = np.array(shap_values)

                    shap_values = np.squeeze(shap_values)
                    if shap_values.ndim == 1:
                        shap_values = shap_values.reshape(1, -1, 1)
                    elif shap_values.ndim == 2:
                        shap_values = np.expand_dims(shap_values, axis=-1)

                    shap_mean = np.mean(np.abs(shap_values), axis=(0, 2))
                    top_timesteps = np.argsort(shap_mean)[-4:][::-1]

                    log("🔍 Top influencing past minutes (LSTM):")
                    for t in top_timesteps:
                        val = shap_mean[t]
                        log(f"   ⏱️ t-{LOOKBACK - t} ({val:.3f})")

                else:
                    log(f"SHAP skip: low bg seqs ({len(background_sequences)} <= 50)")
            else:
                log(f"SHAP skip: insufficient bg ({len(background)} < {LOOKBACK})")
        except Exception as e:
            log(f"SHAP explanation skipped: {e}")

    # ---------- Logging ----------
    log(f"📊 Current rate: {current_rate:.1f} RPM | LSTM 5-min predicted avg: {avg_prediction:.1f} RPM")

    # ────────────────────────────────────────────────
    # CHANGED: Desired-replicas logic – scale purely based on prediction
    # ────────────────────────────────────────────────
    desired = int(np.ceil(avg_prediction / SCALE_OUT_THRESHOLD))
    desired = max(MIN_REPLICAS, min(desired, MAX_REPLICAS))

    if desired > current_replicas:
        return {
            'action': 'scale_out',
            'replicas': desired,
            'reason': f'LSTM predicts higher load ({avg_prediction:.0f} RPM)'
        }

    elif desired < current_replicas:
        return {
            'action': 'scale_in',
            'replicas': desired,
            'reason': f'LSTM predicts lower load ({avg_prediction:.0f} RPM)'
        }

    else:
        return {
            'action': 'none',
            'replicas': desired,
            'reason': 'Load stable'
        }
# ========== MAIN LOOP ==========
def main():

    log(f"🚀 CTPaS Predictor starting – model: {PREDICTOR_MODEL}")

    cycle_number = 0

    while True:

        try:

            cycle_number += 1

            log(f"\n{'='*60}\n🔄 Cycle {cycle_number} CTPaS \n{'='*60}")

            # ---------- Get current replicas ----------
            try:
                current_replicas = get_current_replicas()
            except Exception as e:
                log(f"⚠️ Failed to read current replicas: {e}")
                current_replicas = MIN_REPLICAS

            log(f"Current replicas: {current_replicas}")

            # ---------- Load telemetry data ----------
            raw_data, data = load_data()

            if data is None or len(data) < MIN_RECORDS:
                log("⚠️ Insufficient data, waiting...")
                time.sleep(FREQUENCY_MINUTES * 60)
                continue

            # ---------- LSTM history validation ----------
            if PREDICTOR_MODEL == "lstm":
                if len(data) < LOOKBACK + FORECAST:
                    log(
                        f"Not enough history for LSTM "
                        f"(need {LOOKBACK + FORECAST}, have {len(data)}) – waiting..."
                    )
                    time.sleep(FREQUENCY_MINUTES * 60)
                    continue

            # ---------- Dispatch model ----------
            try:

                if PREDICTOR_MODEL == "xgboost":
                    decision = run_xgboost(raw_data, data, cycle_number)

                elif PREDICTOR_MODEL == "lstm":
                    decision = run_lstm(raw_data, data, cycle_number)

                else:
                    log(f"⚠️ Unknown model '{PREDICTOR_MODEL}', defaulting to XGBoost")
                    decision = run_xgboost(raw_data, data, cycle_number)

            except Exception as e:
                log(f"⚠️ Predictor failure: {e}")
                time.sleep(FREQUENCY_MINUTES * 60)
                continue

            # ---------- Validate decision ----------
            if not isinstance(decision, dict):
                log("⚠️ Invalid decision returned by predictor")
                time.sleep(FREQUENCY_MINUTES * 60)
                continue

            action = decision.get('action', 'none')
            desired = decision.get('replicas', current_replicas)
            reason = decision.get('reason', 'No reason provided')

            # Clamp replicas within safe limits
            desired = max(MIN_REPLICAS, min(desired, MAX_REPLICAS))

            # ---------- Apply cooldown ----------
            if action != 'none':

                active, remaining = cooldown_active(action)

                if active:

                    log(f"⏳ Cooldown active ({remaining}s) – deferring {action}")

                else:

                    # ---------- Scale OUT ----------
                    if action == 'scale_out' and desired > current_replicas:

                        log(f"🚀 Scaling OUT to {desired} – {reason}")

                        try:
                            kubectl_scale(desired)
                            update_cooldown('scale_out')
                        except Exception as e:
                            log(f"⚠️ Failed scaling out: {e}")

                    # ---------- Scale IN ----------
                    elif action == 'scale_in' and desired < current_replicas:

                        log(f"📉 Scaling IN to {desired} – {reason}")

                        try:
                            kubectl_scale(desired)
                            update_cooldown('scale_in')
                        except Exception as e:
                            log(f"⚠️ Failed scaling in: {e}")

                    else:

                        log(
                            f"No replica change needed "
                            f"(current {current_replicas}, desired {desired})"
                        )

            else:

                log(f"No action – {reason}")

        except Exception as e:

            # Absolute safety guard for the predictor loop
            log(f"🔥 Unexpected error in main loop: {e}")

        # ---------- Sleep ----------
        log(f"💤 Sleeping for {FREQUENCY_MINUTES} minute(s)...")

        time.sleep(FREQUENCY_MINUTES * 60)


if __name__ == "__main__":
    main()
'''

def write_configmap():
    indented = "\n".join("    " + line for line in PREDICTOR_PY.split("\n"))
    content = f'''apiVersion: v1
kind: ConfigMap
metadata:
  name: {{{{ include "ctpas.fullname" . }}}}-predictor-script
  namespace: {{{{ .Release.Namespace }}}}
  labels:
    {{{{- include "ctpas.labels" . | nindent 4 }}}}
data:
  predictor.py: |
{indented}
'''
    with open("templates/02-config/configmap.yaml", "w") as f:
        f.write(content)

def write_server():
    with open("templates/03-server/server-deployment.yaml", "w") as f:
        f.write('''apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "ctpas.fullname" . }}-server
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "ctpas.labels" . | nindent 4 }}
    app: {{ include "ctpas.fullname" . }}-server
spec:
  replicas: {{ .Values.server.replicas }}
  selector:
    matchLabels:
      app: {{ include "ctpas.fullname" . }}-server
  template:
    metadata:
      labels:
        app: {{ include "ctpas.fullname" . }}-server
        {{- include "ctpas.labels" . | nindent 8 }}
    spec:
      {{- with .Values.global.securityContext }}
      securityContext:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      volumes:
      - name: shared-data
        {{- if .Values.persistence.enabled }}
        persistentVolumeClaim:
          claimName: {{ include "ctpas.pvcName" . }}
        {{- else }}
        emptyDir: {}
        {{- end }}
      containers:
      - name: server
        image: "{{ .Values.server.image.repository }}:{{ .Values.server.image.tag }}"
        imagePullPolicy: {{ .Values.server.image.pullPolicy }}
        command: ["/app/server"]
        env:
        - name: SERVER_PORT
          value: "8080"
        - name: LOG_FILE
          value: "/data/ctpas-shared/server/server.csv"
        volumeMounts:
        - name: shared-data
          mountPath: /data/ctpas-shared
        ports:
        - containerPort: 8080
        resources:
          {{- toYaml .Values.server.resources | nindent 10 }}
        livenessProbe:
          tcpSocket:
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          tcpSocket:
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
''')
    with open("templates/03-server/server-service.yaml", "w") as f:
        f.write('''apiVersion: v1
kind: Service
metadata:
  name: {{ include "ctpas.fullname" . }}-server-service
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "ctpas.labels" . | nindent 4 }}
    app: {{ include "ctpas.fullname" . }}-server
spec:
  type: {{ .Values.server.service.type }}
  ports:
  - port: {{ .Values.server.service.port }}
    targetPort: 8080
    nodePort: {{ .Values.server.service.nodePort }}
  selector:
    app: {{ include "ctpas.fullname" . }}-server
''')

def write_client_configmap():
    with open("templates/04-config/client-configmap.yaml", "w") as f:
        f.write('''apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "ctpas.fullname" . }}-client-config
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "ctpas.labels" . | nindent 4 }}
data:
  server-ip: "{{ .Values.client.serverIp }}"
''')

def write_client_deployment():
    with open("templates/05-client/client-deployment.yaml", "w") as f:
        f.write('''apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "ctpas.fullname" . }}-client
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "ctpas.labels" . | nindent 4 }}
    app: {{ include "ctpas.fullname" . }}-client
spec:
  replicas: {{ .Values.client.replicas }}
  selector:
    matchLabels:
      app: {{ include "ctpas.fullname" . }}-client
  template:
    metadata:
      labels:
        app: {{ include "ctpas.fullname" . }}-client
        {{- include "ctpas.labels" . | nindent 8 }}
    spec:
      {{- with .Values.global.securityContext }}
      securityContext:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      volumes:
      - name: client-mode
        emptyDir: {}
      containers:
      - name: client
        image: "{{ .Values.client.image.repository }}:{{ .Values.client.image.tag }}"
        imagePullPolicy: {{ .Values.client.image.pullPolicy }}
        command: ["/app/client"]
        env:
        - name: SERVER_IP
          valueFrom:
            configMapKeyRef:
              name: {{ include "ctpas.fullname" . }}-client-config
              key: server-ip
        - name: SERVER_PORT
          value: "{{ .Values.client.serverPort }}"
        - name: SLEEP_VALUE
          value: "{{ .Values.client.sleepValue }}"
        - name: STEP_VALUE
          value: "{{ .Values.client.stepValue }}"
        volumeMounts:
        - name: client-mode
          mountPath: /client
        resources:
          {{- toYaml .Values.client.resources | nindent 10 }}
''')

def write_startup_configmap():
    with open("templates/06-config/predictor-startup.yaml", "w") as f:
        f.write('''apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "ctpas.fullname" . }}-predictor-startup
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "ctpas.labels" . | nindent 4 }}
data:
  start-predictor.sh: |
    #!/bin/bash
    echo "========================================================"
    echo "  CTPaS Predictor (model: ${PREDICTOR_MODEL})"
    echo "  SHAP enabled: ${ENABLE_SHAP}"
    echo "========================================================"

    chmod +x /opt/predictor/predictor.py 2>/dev/null || true

    mkdir -p /data/ctpas-shared/predictor/models
    mkdir -p /data/ctpas-shared/predictor/state
    mkdir -p /data/ctpas-shared/server

    echo "Frequency  set            : ${FREQUENCY_MINUTES} minutes"
    echo "Scale-out threshold set   : ${SCALING_THRESHOLD}"
    echo "Scale-in ratio set        : ${SCALE_IN_THRESHOLD_RATIO:-0.6}"
    echo "Max replicas set          : ${MAX_REPLICAS:-15}"
    echo "Retrain every             : ${RETRAIN_EVERY_N_CYCLES} cycles"
    echo "Model                      : ${PREDICTOR_MODEL}"

    exec python3 /opt/predictor/predictor.py
''')

def write_predictor_deployment():
    with open("templates/07-predictor/predictor-deployment.yaml", "w") as f:
        f.write('''apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "ctpas.fullname" . }}-predictor
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "ctpas.labels" . | nindent 4 }}
    app: {{ include "ctpas.fullname" . }}-predictor
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {{ include "ctpas.fullname" . }}-predictor
  template:
    metadata:
      labels:
        app: {{ include "ctpas.fullname" . }}-predictor
        {{- include "ctpas.labels" . | nindent 8 }}
    spec:
      serviceAccountName: {{ include "ctpas.fullname" . }}-predictor
      {{- with .Values.global.securityContext }}
      securityContext:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      volumes:
      - name: shared-data
        {{- if .Values.persistence.enabled }}
        persistentVolumeClaim:
          claimName: {{ include "ctpas.pvcName" . }}
        {{- else }}
        emptyDir: {}
        {{- end }}
      - name: predictor-script
        configMap:
          name: {{ include "ctpas.fullname" . }}-predictor-script
          items:
          - key: predictor.py
            path: predictor.py
      - name: startup-script
        configMap:
          name: {{ include "ctpas.fullname" . }}-predictor-startup
          defaultMode: 0755
      containers:
      - name: predictor
        image: "{{ .Values.predictor.image.repository }}:{{ .Values.predictor.image.tag }}"
        imagePullPolicy: {{ .Values.predictor.image.pullPolicy }}
        command: ["/bin/bash", "/opt/startup/start-predictor.sh"]
        env:
        - name: DATA_PATH
          value: "/data/ctpas-shared/server/server.csv"
        - name: SCALING_THRESHOLD
          value: "{{ .Values.predictor.scalingThreshold }}"
        - name: FREQUENCY_MINUTES
          value: "{{ .Values.predictor.frequencyMinutes }}"
        - name: MIN_NUM_RECORDS
          value: "{{ .Values.predictor.minNumRecords }}"
        - name: SCALE_IN_THRESHOLD_RATIO
          value: "{{ .Values.predictor.scaleInThreshold | default 0.6 }}"
        - name: MAX_REPLICAS
          value: "{{ .Values.predictor.maxReplicas | default 15 }}"
        - name: RETRAIN_EVERY_N_CYCLES
          value: "{{ .Values.predictor.retrainEveryCycles | default 30 }}"
        - name: PREDICTOR_MODEL
          value: "{{ .Values.predictor.model }}"
        - name: ENABLE_SHAP
          value: "{{ .Values.predictor.enableShap | default true }}"
        - name: SERVER_DEPLOYMENT_NAME
          value: "{{ include "ctpas.fullname" . }}-server"
        volumeMounts:
        - name: shared-data
          mountPath: /data/ctpas-shared
        - name: predictor-script
          mountPath: /opt/predictor/predictor.py
          subPath: predictor.py
        - name: startup-script
          mountPath: /opt/startup
        resources:
          {{- toYaml .Values.predictor.resources | nindent 10 }}
''')

# =============================================================================
# CLIENT AND SERVER SOURCE CODE (unchanged, from earlier working version)
# =============================================================================
CLIENT_CPP = r'''#include <iostream>
#include <string>
#include <thread>
#include <chrono>
#include <atomic>
#include <csignal>
#include <cstdlib>
#include <cmath>
#include <algorithm>
#include <fstream>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <iomanip>
#include <sstream>
#include <ctime>

std::atomic<bool> running(true);
void signal_handler(int) { running = false; }

std::string current_time() {
    auto now = std::chrono::system_clock::now();
    auto now_time = std::chrono::system_clock::to_time_t(now);
    std::tm tm = *std::gmtime(&now_time);
    std::stringstream ss;
    ss << std::put_time(&tm, "%a %b %d %H:%M:%S UTC %Y");
    return ss.str();
}

class TCPClient {
    int sock;
    sockaddr_in server_addr;
public:
    TCPClient(const std::string& ip, int port) {
        sock = socket(AF_INET, SOCK_STREAM, 0);
        server_addr.sin_family = AF_INET;
        server_addr.sin_port = htons(port);
        inet_pton(AF_INET, ip.c_str(), &server_addr.sin_addr);
    }
    bool connect_to_server() { return ::connect(sock, (sockaddr*)&server_addr, sizeof(server_addr)) == 0; }
    void send_message(const std::string& msg) { ::send(sock, msg.c_str(), msg.size(), 0); }
    void close_socket() { ::close(sock); }
};

struct ModeConfig { std::string mode = "NORMAL"; int duration_min = 0; };

ModeConfig read_mode_file() {
    ModeConfig cfg;
    std::ifstream file("/client/mode.txt");
    if (!file.is_open()) {
        // Default to SINE 4 (7 days)
        cfg.mode = "SINE";
        cfg.duration_min = 10080;  // 7 days
        return cfg;
    }
    file >> cfg.mode;
    if (cfg.mode == "FAST" || cfg.mode == "SINE") {
        file >> cfg.duration_min;
        if (cfg.duration_min <= 0) cfg.duration_min = (cfg.mode == "FAST") ? 5 : 2;
    }
    std::transform(cfg.mode.begin(), cfg.mode.end(), cfg.mode.begin(), ::toupper);
    return cfg;
}

int main() {
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    const char* server_ip = getenv("SERVER_IP") ? getenv("SERVER_IP") : "server-service";
    int port = getenv("SERVER_PORT") ? std::atoi(getenv("SERVER_PORT")) : 8080;
    int base_sleep = getenv("SLEEP_VALUE") ? std::atoi(getenv("SLEEP_VALUE")) : 5;
    std::cout << "CTPaS Client started - Dynamic mode enabled (default SINE 4)" << std::endl;
    ModeConfig active_cfg;
    auto mode_start = std::chrono::steady_clock::now();
    int message_count = 0;
    while (running) {
        ModeConfig new_cfg = read_mode_file();
        if (new_cfg.mode != active_cfg.mode) {
            active_cfg = new_cfg;
            mode_start = std::chrono::steady_clock::now();
            std::cout << "=== MODE CHANGED TO " << active_cfg.mode << "   " << current_time() << " ===" << std::endl;
        }
        if (active_cfg.mode == "FAST" || active_cfg.mode == "SINE") {
            auto elapsed = std::chrono::duration_cast<std::chrono::minutes>(std::chrono::steady_clock::now() - mode_start).count();
            if (elapsed >= active_cfg.duration_min) {
                active_cfg.mode = "NORMAL";
                std::cout << "=== Mode auto-reverted to NORMAL   " << current_time() << " ===" << std::endl;
            }
        }
        bool fast = (active_cfg.mode == "FAST");
        bool sine = (active_cfg.mode == "SINE");
        int burst = 1;
        int sleep_ms = base_sleep * 1000;
        if (fast) { burst = 10; sleep_ms = 200; }
        if (sine) {

            static auto minute_start = std::chrono::steady_clock::now();
            static int minute_counter = 0;
            static int requests_this_minute = 0;
            static int sent_this_minute = 0;
            static int per_second = 1;

            auto now = std::chrono::steady_clock::now();
            auto elapsed_sec =
                std::chrono::duration_cast<std::chrono::seconds>(now - minute_start).count();

            if (elapsed_sec >= 60 || requests_this_minute == 0) {
                minute_start = now;
                sent_this_minute = 0;

                double wave = (std::sin(2.0 * M_PI * minute_counter / 4.0) + 1.0) / 2.0;
                int base = 200;
                int amplitude = 150;
                requests_this_minute = base + static_cast<int>(amplitude * wave);
                per_second = std::max(1, requests_this_minute / 60);

                std::cout << "[" << current_time() << "] [SINE] Minute "
                          << minute_counter
                          << " Target RPM: " << requests_this_minute
                          << " | per_sec=" << per_second
                          << std::endl;

                minute_counter = (minute_counter + 1) % 4;
            }

            for (int i = 0; i < per_second; i++) {
                if (sent_this_minute >= requests_this_minute)
                  break;

                TCPClient client(server_ip, port);
                if (client.connect_to_server()) {
                    message_count++;
                    client.send_message("msg " + std::to_string(message_count));
                    client.close_socket();
                    sent_this_minute++;
                }
            }

            std::this_thread::sleep_for(std::chrono::seconds(1));
            continue;
        }
        for (int i = 0; i < burst; i++) {
            TCPClient client(server_ip, port);
            if (client.connect_to_server()) {
                message_count++;
                client.send_message("msg " + std::to_string(message_count));
                client.close_socket();
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(sleep_ms));
    }
    std::cout << "Client stopped" << std::endl;
    return 0;
}
'''

SERVER_CPP = r'''#include <iostream>
#include <string>
#include <thread>
#include <chrono>
#include <atomic>
#include <signal.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <cstring>
#include <sstream>
#include <iomanip>
#include <ctime>
#include <fstream>
#include <mutex>
#include <cmath>
#include <cstdlib>
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

std::atomic<bool> running(true);
std::mutex log_mutex;
std::atomic<int> request_count(0);

void signal_handler(int signal) { running = false; }

std::string current_time() {
    auto now = std::chrono::system_clock::now();
    auto now_time = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;
    std::stringstream ss;
    ss << std::put_time(std::localtime(&now_time), "%Y-%m-%d %H:%M:%S");
    ss << '.' << std::setfill('0') << std::setw(3) << ms.count();
    return ss.str();
}

void handle_client(int client_socket, const char* log_file) {
    char buffer[1024] = {0};
    int bytes = recv(client_socket, buffer, sizeof(buffer), 0);
    if (bytes > 0) {
        int count = ++request_count;
        std::string message(buffer, bytes);
        std::string timestamp = current_time();
        std::string response = "OK [" + timestamp + "] Request #" + std::to_string(count);
        send(client_socket, response.c_str(), response.length(), 0);
        {
            std::lock_guard<std::mutex> lock(log_mutex);
            std::ofstream logfile(log_file, std::ios::app);
            if (logfile.is_open()) {
                logfile << timestamp << "," << count << ",\"" << message.substr(0, 100) << "\",\"" << response << "\"" << std::endl;
            }
        }
        std::cout << timestamp << " - Request #" << count << " from client: " << message.substr(0, 50) << (message.length() > 50 ? "..." : "") << std::endl;
    }
    close(client_socket);
}

int main() {
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    const char* port_str = getenv("SERVER_PORT");
    int port = port_str ? std::atoi(port_str) : 8080;
    const char* log_file = getenv("LOG_FILE");
    if (!log_file) log_file = "/data/ctpas-shared/server/server.csv";
    const char* flag_file = "/data/ctpas-shared/server/boot-strap-done";

    std::cout << "CTPaS Server starting on port " << port << std::endl;

    // ========= BOOTSTRAP SYNTHETIC SINE HISTORY =========
    std::ifstream check_flag(flag_file);
    bool bootstrap_done = check_flag.good();
    check_flag.close();

    if (!bootstrap_done) {
        std::cout << "📈 Bootstrapping historical SINE-4 traffic..." << std::endl;
        if (std::remove(log_file) == 0) {
            std::cout << "Existing server.csv removed" << std::endl;
        }
        std::ofstream init_log(log_file, std::ios::app);
        if (init_log.is_open()) {
            init_log << "timestamp,request_count,client_message,server_response" << std::endl;
            int history_minutes = 180; // 3 hours
            auto now = std::chrono::system_clock::now();
            for (int i = history_minutes; i > 0; --i) {
                auto minute_ts = now - std::chrono::minutes(i);
                auto base_time = std::chrono::system_clock::to_time_t(minute_ts);
                std::stringstream minute_stream;
                minute_stream << std::put_time(std::localtime(&base_time), "%Y-%m-%d %H:%M");
                // SINE-4 (period 4 minutes)
                double t = history_minutes - i;
                double wave = (std::sin(t * M_PI / 2.0) + 1.0) / 2.0;
                double base = 200;
                double amplitude = 150;
                double noise = ((std::rand() % 100) / 100.0 - 0.5) * 4;
                int synthetic_count = static_cast<int>(base + amplitude * wave + noise);
                if (synthetic_count < 1) synthetic_count = 1;

                // Spread requests across the minute
                for (int j = 0; j < synthetic_count; ++j) {
                    int second = (j * 60) / synthetic_count;
                    std::stringstream full_ts;
                    full_ts << minute_stream.str()
                            << ":" << std::setw(2) << std::setfill('0') << second;
                    int count = ++request_count;
                    init_log << full_ts.str()
                             << "," << count
                             << ",\"SYNTHETIC_BOOTSTRAP\",\"OK\""
                             << std::endl;
                }
            }
            init_log.close();
            std::ofstream flag_touch(flag_file);
            flag_touch.close();
            std::cout << "✅ Historical bootstrap complete (realistic sine traffic generated)" << std::endl;
        }
    } else {
        std::cout << "Bootstrap already done - skipping" << std::endl;
    }

    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd == 0) { std::cerr << "Socket creation failed" << std::endl; return 1; }
    int opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    sockaddr_in address;
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = INADDR_ANY;
    address.sin_port = htons(port);

    if (bind(server_fd, (sockaddr*)&address, sizeof(address)) < 0) { std::cerr << "Bind failed" << std::endl; return 1; }
    if (listen(server_fd, 100) < 0) { std::cerr << "Listen failed" << std::endl; return 1; }

    std::cout << current_time() << " - Server ready" << std::endl;
    while (running) {
        sockaddr_in client_addr;
        socklen_t client_len = sizeof(client_addr);
        int client_socket = accept(server_fd, (sockaddr*)&client_addr, &client_len);
        if (client_socket >= 0) {
            std::thread(handle_client, client_socket, log_file).detach();
        }
    }
    std::cout << current_time() << " - Server shutting down" << std::endl;
    close(server_fd);
    return 0;
}
'''

def write_client_source():
    with open("Client/client.cpp", "w") as f:
        f.write(CLIENT_CPP)
    with open("Client/Dockerfile", "w") as f:
        f.write('''FROM ubuntu:22.04
RUN groupadd -r ctpas && useradd -r -g ctpas -s /bin/bash -m ctpas
RUN apt-get update && apt-get install -y g++ build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY client.cpp .
RUN g++ -o client client.cpp -pthread -std=c++17
RUN chown -R ctpas:ctpas /app
USER ctpas
CMD ["/app/client"]
''')

def write_server_source():
    with open("Server/server.cpp", "w") as f:
        f.write(SERVER_CPP)
    with open("Server/Dockerfile", "w") as f:
        f.write('''FROM ubuntu:22.04
RUN groupadd -r ctpas && useradd -r -g ctpas -s /bin/bash -m ctpas
RUN apt-get update && apt-get install -y g++ build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server.cpp .
RUN g++ -o server server.cpp -pthread -std=c++17
RUN chown -R ctpas:ctpas /app
USER ctpas
CMD ["/app/server"]
''')

def write_predictor_dockerfile():
    with open("Dockerfile-predictor", "w") as f:
        f.write('''FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TF_CPP_MIN_LOG_LEVEL=2

RUN groupadd -r ctpas && useradd -r -g ctpas -s /bin/bash -m ctpas
WORKDIR /app

RUN apt-get update && apt-get install -y curl bc && rm -rf /var/lib/apt/lists/*

ARG KUBECTL_VERSION=v1.29.0
RUN curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" && \\
    chmod +x kubectl && mv kubectl /usr/local/bin/

RUN pip install --no-cache-dir \\
    numpy==1.24.3 \\
    pandas==1.5.3 \\
    xgboost==2.0.3 \\
    scikit-learn==1.3.0 \\
    joblib==1.3.2 \\
    tensorflow==2.13.1 \\
    shap==0.42.1

RUN mkdir -p /data/ctpas-shared/predictor/models \\
             /data/ctpas-shared/predictor/state \\
             /data/ctpas-shared/server && \\
    chown -R ctpas:ctpas /data/ctpas-shared

USER ctpas
CMD ["sleep", "infinity"]
''')

# =============================================================================
# INSTALLATION SCRIPTS
# =============================================================================
def write_setup_env():
    with open("setup_env.sh", "w") as f:
        f.write("""#!/bin/bash
set -e
echo "Step 1: Installing Docker, Helm, and Dependencies..."
sudo apt-get update
sudo apt-get install apt-transport-https ca-certificates curl software-properties-common unzip -y --allow-change-held-packages
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io -y --allow-change-held-packages

echo "Installing Helm..."
if ! command -v helm &> /dev/null; then
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash || {
        HELM_VER="v3.13.1"
        curl -L https://get.helm.sh/helm-${HELM_VER}-linux-amd64.tar.gz -o helm.tar.gz
        tar -zxvf helm.tar.gz
        sudo mv linux-amd64/helm /usr/local/bin/helm
        rm -rf linux-amd64 helm.tar.gz
    }
else
    echo "Helm already installed."
fi

echo "Configuring Containerd Registry Mirror..."
sudo mkdir -p /etc/containerd/certs.d/docker.io
cat <<EOF | sudo tee /etc/containerd/config.toml
version = 2
[plugins."io.containerd.grpc.v1.cri".registry]
  config_path = "/etc/containerd/certs.d"
EOF
cat <<EOF | sudo tee /etc/containerd/certs.d/docker.io/hosts.toml
server = "https://docker.io"
[host."http://docker-registry-mirror.kodekloud.com"]
  capabilities = ["pull", "resolve"]
EOF
sudo systemctl restart containerd
sudo systemctl restart docker

echo "Shared Storage..."
sudo mkdir -p /data/ctpas-shared/predictor/models
sudo mkdir -p /data/ctpas-shared/predictor/state
sudo mkdir -p /data/ctpas-shared/server
sudo chmod -R 777 /data/ctpas-shared

echo "Building and Sideloading Images..."
docker build -t ctpas-server:latest -f Server/Dockerfile Server/
docker build -t ctpas-client:latest -f Client/Dockerfile Client/
docker build -t ctpas-predictor:latest -f Dockerfile-predictor .

for img in ctpas-server ctpas-client ctpas-predictor; do
    echo "Injecting $img into k8s.io namespace..."
    docker save $img:latest -o $img.tar
    sudo ctr -n=k8s.io images import $img.tar
    rm $img.tar
done
echo "Environment Ready!"
""")
    os.chmod("setup_env.sh", 0o755)

def write_install():
    with open("install.sh", "w") as f:
        f.write(r'''#!/bin/bash
set -e
echo "========================================================"
echo "CTPaS - Containerized Traffic Predictor as a Service"
echo "Pluggable Models: XGBoost+SHAP / LSTM+SHAP"
echo "========================================================"

command -v docker >/dev/null 2>&1 || { echo "Docker required but not installed."; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl required but not installed."; exit 1; }
command -v helm >/dev/null 2>&1 || { echo "Helm required but not installed."; exit 1; }
echo "Prerequisites check passed"

if ! kubectl cluster-info >/dev/null 2>&1; then
    echo "Cannot connect to Kubernetes cluster"; exit 1
fi
echo "Connected to Kubernetes cluster: $(kubectl config current-context)"

NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null || echo "")
if [ -z "$NODE_IP" ]; then
    NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}' 2>/dev/null || echo "")
fi
[ -n "$NODE_IP" ] && echo "Node IP: $NODE_IP" || echo "Could not determine node IP"
if [ -n "$NODE_IP" ] && [ -f "values.yaml" ]; then
    sed -i.bak "s/serverIp:.*/serverIp: $NODE_IP/" values.yaml
fi

echo "Building Docker images..."
docker build -t ctpas-server:latest -f Server/Dockerfile Server/ || { echo "Server build failed"; exit 1; }
docker build -t ctpas-client:latest -f Client/Dockerfile Client/ || { echo "Client build failed"; exit 1; }
docker build --build-arg KUBECTL_VERSION=v1.29.0 -t ctpas-predictor:latest -f Dockerfile-predictor . || { echo "Predictor build failed"; exit 1; }
echo "All images built"

docker run --rm ctpas-predictor:latest python -c "import tensorflow as tf; print(f'TF: {tf.__version__}')"
docker run --rm ctpas-predictor:latest kubectl version --client

kubectl create namespace ctpas --dry-run=client -o yaml | kubectl apply -f -

STORAGE_CLASS=$(kubectl get storageclass -o name | head -1 | cut -d'/' -f2 || echo "standard")
echo "Using storage class: $STORAGE_CLASS"
[ -f "values.yaml" ] && sed -i.bak "s/storageClassName:.*/storageClassName: \"$STORAGE_CLASS\"/" values.yaml

helm upgrade --install ctpas . \
    --namespace ctpas \
    --create-namespace \
    --wait \
    --timeout 5m \
    --debug \
    --set client.serverIp="$NODE_IP" \
    --set persistence.storageClassName="$STORAGE_CLASS" || {
    echo "Helm installation failed"
    echo "  kubectl get pv && kubectl get storageclass"
    exit 1
}

echo "Helm chart installed"
sleep 15
kubectl get pods -n ctpas -o wide
kubectl get svc -n ctpas
kubectl get pvc -n ctpas

echo ""
echo "========================================================"
echo "Server NodePort : $NODE_IP:30007"
echo "Current model   : $(helm get values ctpas -n ctpas | grep model | head -1)"
echo ""
echo "Monitor predictor: kubectl logs -n ctpas -l app=ctpas-predictor -f"
echo "Watch replicas:    kubectl get deployment -n ctpas ctpas-server -w"
echo ""
echo "Switch model: helm upgrade ctpas . --set predictor.model=lstm"
echo ""
echo "Traffic modes (override default SINE-4):"
echo "  kubectl exec -n ctpas deploy/ctpas-client -- sh -c \"echo SINE 4 > /client/mode.txt\""
echo "  kubectl exec -n ctpas deploy/ctpas-client -- sh -c \"echo FAST 5 > /client/mode.txt\""
echo "  kubectl exec -n ctpas deploy/ctpas-client -- sh -c \"echo NORMAL > /client/mode.txt\""
echo ""
echo "Uninstall: ./uninstall.sh"
echo "CTPaS installation complete!"
''')
    os.chmod("install.sh", 0o755)

def write_uninstall():
    with open("uninstall.sh", "w") as f:
        f.write('''#!/bin/bash
echo "CTPaS Uninstallation"
read -p "Are you sure? (y/N): " -n 1 -r; echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then echo "Cancelled."; exit 0; fi
kubectl exec -it deployments/ctpas-server -n ctpas -- sh -c "rm -rf /data/ctpas-shared/server/*" 2>/dev/null || true
helm uninstall ctpas -n ctpas 2>/dev/null || true
kubectl delete namespace ctpas 2>/dev/null || true
kubectl delete pvc -n ctpas --all 2>/dev/null || true
kubectl delete pv -l app=ctpas 2>/dev/null || true
kubectl delete serviceaccount -l app=ctpas-predictor 2>/dev/null || true
docker rmi ctpas-server:latest ctpas-client:latest ctpas-predictor:latest 2>/dev/null || true
echo "CTPaS uninstalled!"
echo "To clean data: sudo rm -rf /data/ctpas-shared"
''')
    os.chmod("uninstall.sh", 0o755)

def write_quick_test():
    with open("quick-test.sh", "w") as f:
        f.write('''#!/bin/bash
echo "CTPaS Quick Test"
echo "================================"
echo "1. Pods:"; kubectl get pods -n ctpas -o wide
echo ""; echo "2. Services:"; kubectl get svc -n ctpas
echo ""; echo "3. Storage:"; kubectl get pvc -n ctpas; kubectl get pv | grep ctpas
echo ""; echo "4. Server logs:"; kubectl logs -n ctpas -l app=ctpas-server --tail=5 2>/dev/null || echo "Not ready"
echo ""; echo "5. Client logs:"; kubectl logs -n ctpas -l app=ctpas-client --tail=5 2>/dev/null || echo "Not ready"
echo ""; echo "6. Predictor logs:"; kubectl logs -n ctpas -l app=ctpas-predictor --tail=15 2>/dev/null || echo "Not ready"
echo ""; echo "Quick test complete!"
echo "Monitor: kubectl logs -n ctpas -l app=ctpas-predictor -f"
echo "Watch replicas: kubectl get deployment -n ctpas ctpas-server -w"
''')
    os.chmod("quick-test.sh", 0o755)

def write_verify():
    with open("verify-ctpas.sh", "w") as f:
        f.write('''#!/bin/bash
echo "Verifying CTPaS Installation"
echo "=============================="
echo "1. Model switch in values.yaml:"
grep "model:" values.yaml
echo "2. Predictor script contains both models:"
echo "3. Environment variable in deployment:"
echo "4. Dockerfile includes TensorFlow and XGBoost:"
echo "Verification complete!"
''')
    os.chmod("verify-ctpas.sh", 0o755)

   
def create_project():
   print("CTPaS - Containerized Traffic Predictor as a Service")
   print("=" * 60)
   print("Creating installation package with pluggable models (XGBoost/LSTM)...")

   directories = [
   "templates/01-rbac", "templates/02-config", "templates/03-server",
   "templates/04-config", "templates/05-client", "templates/06-config",
   "templates/07-predictor", "templates/08-storage", "Client", "Server"
   ]
   for directory in directories:
      os.makedirs(directory, exist_ok=True)
      print(f"Created: {directory}")

   write_chart_yaml()
   write_values_yaml()
   write_helpers()
   write_storage()
   write_rbac()
   write_configmap()
   write_server()
   write_client_configmap()
   write_client_deployment()
   write_startup_configmap()
   write_predictor_deployment()
   write_client_source()
   write_server_source()
   write_predictor_dockerfile()
   write_setup_env()
   write_install()
   write_uninstall()
   write_quick_test()
   write_verify()
   #write_readme()

   zip_name = "ctpas-project.zip"
   with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
      for root, dirs, files in os.walk("."):
         for file in files:
            filepath = os.path.join(root, file)
            if "zip" not in file and "ctpas_one_touch" not in file:
                zipf.write(filepath)

   print(f"\n✅ Project creation complete! File: {zip_name}")
   print("\nTo install:")
   print(" unzip ctpas-project.zip")
   print(" cd ctpas-project")
   print(" chmod +x *.sh")
   print(" ./setup_env.sh # if Docker/Helm not installed")
   print(" ./install.sh # deploys with default model (xgboost)")
   print("\nAfter install, you can switch models with:")
   print(" helm upgrade ctpas . --set predictor.model=lstm")
   # After zip creation, proceed with installation
   print("\n" + "="*60)
   print("Proceeding with installation from generated files...")
   print("="*60)

   import subprocess
   import glob

   # Make all shell scripts executable
   sh_files = glob.glob("*.sh")
   if sh_files:
       subprocess.run(["chmod", "+x"] + sh_files, check=True)

   # Run setup_env.sh (optional, but we'll run it)
   print("\n🔧 Running environment setup (setup_env.sh)...")
   subprocess.run(["./setup_env.sh"], check=True)

   # Run install.sh
   print("\n🚀 Running installation (install.sh)...")
   subprocess.run(["./install.sh"], check=True)

   print("\n✅ CTPaS is now deployed! Check pods: kubectl get pods -n ctpas")

if __name__ == "__main__":
    create_project()

  