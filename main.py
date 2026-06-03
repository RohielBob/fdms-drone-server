import os
import shutil
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from fastapi import UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, validator
from openpyxl import Workbook, load_workbook
from fastapi import WebSocket, WebSocketDisconnect
from typing import List
from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials, db

import asyncio
import json

counter = 0

# =====================================================
# CONFIG
# =====================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FIREBASE_CREDENTIALS = os.path.join(BASE_DIR, "firebase_key.json")
EXCEL_FILE = os.path.join(BASE_DIR, "drone_data.xlsx")
SQLITE_DB = os.path.join(BASE_DIR, "drone_data.db")

app = FastAPI(
    title="FDMS Drone API",
    description="API de surveillance et d’analyse des données de vol du drone du Groupe 6",
    version="1.0.0"
)
class ConnectionManager:
    def __init__(self):
        self.active_connections = []
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self.lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        try:
            await websocket.send_text(message)
        except:
            await self.disconnect(websocket)

    async def broadcast(self, data: dict):
        message = json.dumps(data)
        dead = []

        async with self.lock:
            for connection in self.active_connections:
                try:
                    await connection.send_text(message)
                except:
                    dead.append(connection)

            for d in dead:
                if d in self.active_connections:
                    self.active_connections.remove(d)

manager = ConnectionManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

excel_lock = threading.Lock()
db_lock = threading.Lock()

# =====================================================
# FIREBASE
# =====================================================
# =====================================================
# FIREBASE (VERSION PRO SAFE)
# =====================================================
FIREBASE_DB_URL = "https://drone-fdm-project-groupe-6-default-rtdb.firebaseio.com/"
firebase_enabled = False

def init_firebase():
    global firebase_enabled

    if not os.path.exists(FIREBASE_CREDENTIALS):
        print("❌ firebase_key.json introuvable")
        firebase_enabled = False
        return

    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(FIREBASE_CREDENTIALS)
            firebase_admin.initialize_app(cred, {
                "databaseURL": FIREBASE_DB_URL
            })

        # 🔥 TEST RÉEL
        ref = db.reference("health_check")
        ref.set({
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat()
        })

        firebase_enabled = True
        print("✅ Firebase connecté")

    except Exception as e:
        print("🚨 Firebase erreur:", e)
        firebase_enabled = False


# 👉 IMPORTANT : lancement au démarrage
init_firebase()

def check_firebase():
    if not firebase_enabled:
        return "désactivé"

    try:
        ref = db.reference("health_check")
        data = ref.get()

        if data:
            return "actif"
        else:
            return "instable"

    except:
        return "erreur"

# =====================================================
# MODELE (FIX 422 ICI)
# =====================================================
class DroneData(BaseModel):
    Flight_ID: str = "MISSION"
    Date: Optional[str] = None
    timestamp: Optional[int]
    altitude: float
    vitesse: float
    ax: float
    ay: float
    az: float
    roll: float
    pitch: float
    yaw: float
    pression: float
    temperature: float
    batterie: float = 100.0

    @validator("timestamp", pre=True, always=True)
    def validate_ts(cls, v):
        return validate_timestamp(v)


# =====================================================
# EXCEL INIT
# =====================================================

# =====================================================
# SQLITE INIT (FIX IMPORTANT)
# =====================================================
def init_db():
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drone_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Flight_ID TEXT,
            Date TEXT,
            timestamp INTEGER,
            altitude REAL,
            vitesse REAL,
            ax REAL,
            ay REAL,
            az REAL,
            roll REAL,
            pitch REAL,
            yaw REAL,
            pression REAL,
            temperature REAL,
            batterie REAL
        )
    """)

    conn.commit()
    conn.close()

init_db()


def get_db_connection():
    conn = sqlite3.connect(SQLITE_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def validate_timestamp(ts):
    try:
        # 🔥 None ou vide
        if ts is None:
            return int(datetime.utcnow().timestamp())

        # 🔥 string → int
        if isinstance(ts, str):
            ts = int(float(ts))

        # 🔥 float → int
        if isinstance(ts, float):
            ts = int(ts)

        # 🔥 valeur négative ou absurde
        if ts < 0:
            return int(datetime.utcnow().timestamp())

        return ts

    except:
        # fallback sécurité
        return int(datetime.utcnow().timestamp())

# =====================================================
# EXCEL (VERSION PRO SAFE)
# =====================================================

EXCEL_HEADERS = [
    "Flight_ID","Date","timestamp","altitude","vitesse",
    "ax","ay","az","roll","pitch","yaw",
    "pression","temperature","batterie"
]

def init_excel():
    if not os.path.exists(EXCEL_FILE):
        wb = Workbook()
        ws = wb.active
        ws.title = "Données Drone"
        ws.append(EXCEL_HEADERS)
        wb.save(EXCEL_FILE)
        print("✅ Excel créé")

init_excel()

def append_to_excel(data_dict):
    temp_file = EXCEL_FILE + ".tmp"

    try:
        with excel_lock:
            wb = load_workbook(EXCEL_FILE)
            ws = wb.active

            row = [data_dict.get(h) for h in EXCEL_HEADERS]
            ws.append(row)

            wb.save(temp_file)
            wb.close()

            # 🔥 remplace fichier seulement si OK
            shutil.move(temp_file, EXCEL_FILE)

    except Exception as e:
        print("🚨 Excel safe write error:", e)


# =====================================================
# ALERTES
# =====================================================
def generate_alerts(data_dict):
    alerts = []

    if data_dict.get("temperature", 0) < -50 or data_dict.get("temperature", 0) > 150:
        alerts.append("Température inhabituelle")

    if data_dict.get("altitude", 0) < -100 or data_dict.get("altitude", 0) > 10000:
        alerts.append("Altitude inhabituelle")

    if data_dict.get("vitesse", 0) < 0 or data_dict.get("vitesse", 0) > 300:
        alerts.append("Vitesse inhabituelle")

    if data_dict.get("pression", 0) < 300 or data_dict.get("pression", 0) > 1200:
        alerts.append("Pression inhabituelle")

    if data_dict.get("roll", 0) < -180 or data_dict.get("roll", 0) > 180:
        alerts.append("Roll inhabituel")

    if data_dict.get("pitch", 0) < -180 or data_dict.get("pitch", 0) > 180:
        alerts.append("Pitch inhabituel")

    if data_dict.get("yaw", 0) < -360 or data_dict.get("yaw", 0) > 360:
        alerts.append("Yaw inhabituel")

    return alerts


# =====================================================
# HOME
# =====================================================
@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Accueil - FDMS Drone Intelligence</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;800&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { font-family: 'Poppins', sans-serif; background-color: #f8fafc; color: #1e293b; }
        .glass-card { background: rgba(255, 255, 255, 0.8); backdrop-filter: blur(12px); border-radius: 30px; border: 1px solid rgba(255, 255, 255, 0.5); box-shadow: 0 10px 40px rgba(0,0,0,0.03); }
        .gradient-text { background: linear-gradient(90deg, #3b82f6, #60a5fa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .mission-icon { width: 60px; height: 60px; background: #eff6ff; color: #3b82f6; display: flex; align-items: center; justify-content: center; border-radius: 18px; font-size: 24px; margin-bottom: 20px; }
        header { background: rgba(255, 255, 255, 0.95); backdrop-filter: blur(10px); position: fixed; width: 100%; top: 0; z-index: 1000; border-bottom: 1px solid #e2e8f0; }
        
        /* Style des boutons de la barre latérale */
        .side-btn {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 18px;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            color: #cbd5e1;
            text-decoration: none;
            font-weight: 500;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            width: 100%;
            text-align: left;
        }

        .side-btn i { width: 20px; text-align: center; }

        .side-btn:hover {
            background: #3b82f6;
            color: white;
            transform: translateX(8px);
            box-shadow: 0 4px 15px rgba(59, 130, 246, 0.4);
        }

        .sidebar-open { left: 0 !important; }
    </style>
</head>
<body class="pt-24">

    <button onclick="toggleSidebar()" class="fixed top-5 left-5 z-[2000] bg-blue-600 text-white p-3 rounded-xl shadow-lg hover:bg-blue-700 transition-all">
        <i class="fas fa-bars"></i>
    </button>

    <div id="sidebar" class="fixed top-0 left-[-300px] w-[280px] h-full bg-slate-900 z-[1500] shadow-2xl transition-all duration-300 ease-in-out p-6 pt-20">
        <div class="flex flex-col gap-3">
            <a href="/dashboard" class="side-btn"><i class="fas fa-chart-line"></i> Dashboard</a>
            <a href="/docs" class="side-btn"><i class="fas fa-file-code"></i> API Docs</a>
            <a href="/latest-data" class="side-btn"><i class="fas fa-clock"></i> Latest Data</a>
            <a href="/graph-data" class="side-btn"><i class="fas fa-database"></i> All Data</a>
            <a href="/docs#/default/receive_drone_data_drone_data_post" class="side-btn"><i class="fas fa-satellite-dish"></i> Réception</a>
            <a href="https://console.firebase.google.com/" target="_blank" class="side-btn"><i class="fab fa-google"></i> Firebase</a>
            <a href="/export-excel" class="side-btn"><i class="fas fa-file-excel"></i> Export Excel</a>
            <a href="/health" class="side-btn"><i class="fas fa-heartbeat"></i> Health Check</a>
            <button onclick="resetData()" class="side-btn text-red-400 border-red-900/30 hover:bg-red-900/20"><i class="fas fa-trash"></i> Reset Data</button>
        </div>
    </div>

    <div id="overlay" onclick="toggleSidebar()" class="fixed inset-0 bg-black/50 hidden z-[1400]"></div>

    <header class="py-4 px-8 flex justify-between items-center">
        <div class="text-2xl font-bold text-slate-900 ml-12">FDMS<span class="text-blue-500"> G-06</span></div>
        <nav class="hidden md:block">
            <ul class="flex gap-8 list-none">
                <li><a href="/" class="text-blue-600 font-bold">Accueil</a></li>
            </ul>
        </nav>
        <a href="/dashboard" class="bg-blue-600 text-white px-6 py-2 rounded-full font-semibold hover:bg-blue-700 transition shadow-lg shadow-blue-200">Live Monitor</a>
    </header>

    <main class="max-w-6xl mx-auto px-6 mt-16 mb-20">
        <div class="text-center mb-16">
            <h1 class="text-6xl font-extrabold text-slate-900 mb-6 tracking-tight">FDMS <span class="gradient-text">Control Center</span></h1>
            <p class="text-slate-500 text-xl max-w-2xl mx-auto font-light">
                Bienvenue sur le serveur FDMS du <strong>Groupe 6</strong>. Cette station de contrôle avancée permet la surveillance télémétrique et l'analyse de données en temps réel d'un drone.
            </p>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-8 mb-16">
            <div class="glass-card p-8">
                <div class="mission-icon"><i class="fas fa-bolt"></i></div>
                <h3 class="text-xl font-bold mb-3">Temps Réel</h3>
                <p class="text-slate-500 text-sm">Visualisation instantanée des données : altitude, vitesse, température, batterie, pression, orientation et accélération.</p>
            </div>
            <div class="glass-card p-8">
                <div class="mission-icon"><i class="fas fa-database"></i></div>
                <h3 class="text-xl font-bold mb-3">Archivage</h3>
                <p class="text-slate-500 text-sm">Stockage sécurisé sur SQLite et Firebase, avec exportation automatique vers Excel pour analyse.</p>
            </div>
            <div class="glass-card p-8">
                <div class="mission-icon"><i class="fas fa-shield-alt"></i></div>
                <h3 class="text-xl font-bold mb-3">Sécurité</h3>
                <p class="text-slate-500 text-sm">Algorithmes de détection d'anomalies et alertes automatiques en cas de dépassement de seuils.</p>
            </div>
        </div>

        <div class="glass-card p-10 bg-slate-900 text-white border-none relative overflow-hidden">
            <div class="relative z-10 flex flex-col md:flex-row justify-between items-center gap-8">
                <div>
                    <h2 class="text-3xl font-bold mb-4">Prêt pour le décollage ?</h2>
                    <p class="text-slate-400">Accédez au panneau de contrôle pour voir les données en direct.</p>
                </div>
                <a href="/dashboard" class="bg-white text-slate-900 px-8 py-4 rounded-2xl font-bold hover:scale-105 transition shadow-xl">Accéder au Dashboard →</a>
            </div>
            <div class="absolute top-0 right-0 opacity-10 transform translate-x-1/4 -translate-y-1/4">
                <i class="fas fa-plane-departure text-[200px]"></i>
            </div>
        </div>
    </main>

    <footer class="text-center py-12 text-slate-400 text-sm border-t border-slate-200">
        <p>&copy; 2026 - Projet FDMS Ingénierie. Développé par le Groupe 6.</p>
    </footer>
    
    <script>
        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            const overlay = document.getElementById('overlay');
            sidebar.classList.toggle('sidebar-open');
            overlay.classList.toggle('hidden');
        }

        async function resetData() {
            if(confirm("Êtes-vous sûr de vouloir supprimer TOUTES les données ?")) {
                try {
                    const response = await fetch('/delete-all', { method: 'DELETE' });
                    if(response.ok) {
                        alert("Données réinitialisées avec succès !");
                        location.reload();
                    }
                } catch (error) {
                    alert("Erreur lors de la réinitialisation.");
                }
            }
        }
    </script>
</body>
</html>
"""

# =====================================================
# POST DRONE DATA (MISSION PLANNER SAFE)
# =====================================================
@app.post("/drone-data")
async def receive_drone_data(data: DroneData):

    data_dict = data.dict()
    # 🔥 VALIDATION TIMESTAMP
    data_dict["timestamp"] = validate_timestamp(data_dict.get("timestamp"))

    if data_dict.get("batterie") is None:
        data_dict["batterie"] = 100.0

    alerts = generate_alerts(data_dict)

    # =========================
    # SQLITE (VERSION PROPRE)
    # =========================
    with db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO drone_data (
                    Flight_ID, Date, timestamp, altitude, vitesse,
                    ax, ay, az, roll, pitch, yaw,
                    pression, temperature, batterie
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.Flight_ID, data.Date, data_dict["timestamp"], data.altitude, data.vitesse,
                data.ax, data.ay, data.az, data.roll, data.pitch, data.yaw,
                data.pression, data.temperature, data.batterie
            ))

            conn.commit()

        finally:
            conn.close()

    # =========================
    # EXCEL
    # =========================
    append_to_excel(data_dict)

    # =========================
    # FIREBASE
    # =========================
    if firebase_enabled:
        try:
            db.reference("drone_data").push(data_dict)
        except Exception as e:
            print("Firebase error:", e)

    # =========================
    # WEBSOCKET (TEMPS RÉEL)
    # =========================
    asyncio.create_task(manager.broadcast(data_dict))

    return {
        "status": "ok",
        "alerts": alerts,
        "data": data_dict
    }


# =====================================================
# LATEST DATA (SAFE)
# =====================================================
@app.get("/latest-data")
def latest_data():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM drone_data ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"message": "Aucune donnée"}

    data = dict(row)
    data["alerts"] = generate_alerts(data)
    return data


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        await manager.disconnect(websocket)

    except Exception:
        await manager.disconnect(websocket)

# =====================================================
# GRAPH DATA
# =====================================================
@app.get("/graph-data")
def graph_data():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM drone_data
        ORDER BY id DESC
        LIMIT 100
    """)

    rows = cursor.fetchall()
    conn.close()

    data = []

    for row in reversed(rows):
        d = dict(row)

        d["timestamp"] = validate_timestamp(d.get("timestamp"))

        # nettoyage
        for key in d:
            if d[key] is None:
                d[key] = 0

        data.append(d)

    return data

# =====================================================
# IMPORT EXCEL (SIMULATION MODE)
# =====================================================
@app.post("/upload-excel")
async def upload_excel(file: UploadFile = File(...)):
    if not file.filename.endswith(".xlsx"):
        return {"error": "Format invalide, fichier .xlsx requis"}

    try:
        wb = load_workbook(file.file, data_only=True)
        ws = wb.active

        rows = list(ws.iter_rows(values_only=True))

        if len(rows) < 2:
            return {"error": "Fichier vide ou invalide"}

        headers = rows[0]
        data = []

        for row in rows[1:]:
            d = dict(zip(headers, row))

            for key in d:
                if d[key] is None:
                    d[key] = 0

            d["timestamp"] = validate_timestamp(d.get("timestamp"))
            data.append(d)

        return {
            "status": "ok",
            "data": data
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/health-json")
def health():
    try:
        excel_exists = os.path.exists(EXCEL_FILE)
        sqlite_exists = os.path.exists(SQLITE_DB)

        total_data = 0
        last_timestamp = None

        if sqlite_exists:
            conn = sqlite3.connect(SQLITE_DB)
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM drone_data")
            total_data = cursor.fetchone()[0]

            cursor.execute("SELECT timestamp FROM drone_data ORDER BY id DESC LIMIT 1")
            last_row = cursor.fetchone()

            if last_row:
                last_timestamp = int(last_row[0]) if last_row else None

            conn.close()

        return {
            "status": "ok",
            "firebase": check_firebase(),
            "excel": "présent" if excel_exists else "absent",
            "sqlite": "présent" if sqlite_exists else "absent",
            "nombre_donnees": total_data,
            "derniere_reception": last_timestamp if last_timestamp else "aucune donnée",
            "mode_stockage": "SQLite + Excel + Firebase"
        }

    except Exception as e:
        return {
            "status": "erreur",
            "details": str(e)
        }


@app.get("/health", response_class=HTMLResponse)
def health_dashboard():
    return """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>FDMS Health</title>

<script src="https://cdn.tailwindcss.com"></script>

<style>
body {
    background: linear-gradient(135deg, #e0f2fe, #f8fafc);
    font-family: 'Inter', sans-serif;
}
.card {
    background: white;
    border-radius: 18px;
    padding: 20px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.05);
}
.ok { color: #10b981; }
.bad { color: #ef4444; }
.warn { color: #f59e0b; }
</style>
</head>

<body class="flex items-center justify-center min-h-screen">

<div class="w-full max-w-5xl space-y-6">

    <h1 class="text-3xl font-black text-center text-slate-700">
    💓 FDMS Health Monitor
    <span id="liveDot" style="
        display:inline-block;
        width:10px;
        height:10px;
        border-radius:50%;
        background:red;
        margin-left:10px;
    "></span>
</h1>

    <!-- ALERT BAR -->
    <div id="alertBox" class="hidden p-4 rounded-xl font-bold text-center"></div>

    <!-- STATUS -->
    <div class="grid grid-cols-4 gap-4">
        <div class="card text-center">Server<br><b id="server"></b></div>
        <div class="card text-center">Firebase<br><b id="firebase"></b></div>
        <div class="card text-center">SQLite<br><b id="sqlite"></b></div>
        <div class="card text-center">Excel<br><b id="excel"></b></div>
    </div>

    <!-- DATA -->
        <div class="grid grid-cols-5 gap-4">
        <div class="card text-center">Données<br><b id="count"></b></div>
        <div class="card text-center">Dernière réception<br><b id="last"></b></div>
        <div class="card text-center">Mode<br><b id="mode"></b></div>
        <div class="card text-center">
            Ping<br>
            <b id="ping">--</b> ms
        </div>

        <div class="card text-center">
            Uptime<br>
            <b id="uptime">--</b>
            </div>
    </div>

</div>

<script>

let lastCount = 0;
let startTime = Date.now();
let errorHistory = [];

// ==========================
// 🔴 LIVE DOT
// ==========================
function setLive(status) {
    const dot = document.getElementById("liveDot");

    if (!dot) return;

    if (status === "ok") {
        dot.style.background = "#10b981";
        dot.style.boxShadow = "0 0 10px #10b981";
    } else if (status === "warn") {
        dot.style.background = "#f59e0b";
        dot.style.boxShadow = "0 0 10px #f59e0b";
    } else {
        dot.style.background = "#ef4444";
        dot.style.boxShadow = "0 0 10px #ef4444";
    }
}

// ==========================
// 🚨 ALERT SYSTEM
// ==========================
function showAlert(message, type="bad") {
    const box = document.getElementById("alertBox");
    box.classList.remove("hidden");

    box.className =
        "p-4 rounded-xl font-bold text-center " +
        (type === "bad"
            ? "bg-red-100 text-red-600"
            : type === "warn"
            ? "bg-yellow-100 text-yellow-600"
            : "bg-green-100 text-green-600");

    box.innerText = message;

    errorHistory.push({
        time: new Date().toLocaleTimeString(),
        message
    });

    if (errorHistory.length > 5) errorHistory.shift();
}

// ==========================
// ⚡ FETCH HEALTH
// ==========================
async function fetchHealth() {
    const start = performance.now();

    try {
        const res = await fetch("/health-json", { cache: "no-store" });
        const data = await res.json();

        const ping = Math.round(performance.now() - start);

        // UI UPDATE
        document.getElementById("server").innerText = data.status;
        document.getElementById("firebase").innerText = data.firebase;
        document.getElementById("sqlite").innerText = data.sqlite;
        document.getElementById("excel").innerText = data.excel;
        document.getElementById("count").innerText = data.nombre_donnees;
        document.getElementById("mode").innerText = data.mode_stockage;

        document.getElementById("ping").innerText = ping;

        // UPTIME
        const uptimeMs = Date.now() - startTime;
        document.getElementById("uptime").innerText =
            Math.floor(uptimeMs / 60000) + " min";

        // LAST DATA
        if (data.derniere_reception && data.derniere_reception !== "aucune donnée") {
            const d = new Date(data.derniere_reception * 1000);
            document.getElementById("last").innerText = d.toLocaleString();
        } else {
            document.getElementById("last").innerText = "Aucune";
        }

        // LOGIC STATUS
        let status = "ok";

        if (ping > 800) status = "warn";

        if (data.firebase !== "actif") {
            showAlert("🚨 Firebase OFFLINE", "bad");
            status = "bad";
        }
        else if (data.sqlite !== "présent" || data.excel !== "présent") {
            showAlert("⚠️ Stockage instable", "warn");
            status = "warn";
        }
        else if (lastCount !== 0 && data.nombre_donnees === lastCount) {
            showAlert("⚠️ Drone inactif", "warn");
            status = "warn";
        }
        else {
            showAlert("✅ Système opérationnel", "ok");
        }

        setLive(status);

        lastCount = data.nombre_donnees;

    } catch (e) {
        setLive("bad");
        showAlert("🚨 SERVEUR DOWN", "bad");
    }
}
// ==========================
// 📌 INPUT FILE BUTTON
// ==========================


// LOOP
window.onload = () => {
    fetchHealth();
    setInterval(fetchHealth, 3000);
};

</script>

</body>
</html>
"""
# =====================================================
# EXPORT EXCEL
# =====================================================
@app.get("/export-excel")
def export_excel():
    return FileResponse(EXCEL_FILE)


# =====================================================
# RESET DATA
# =====================================================
@app.delete("/delete-all")
def reset_data():
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM drone_data")
    conn.commit()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.append([
        "Flight_ID","Date","timestamp","altitude","vitesse",
        "ax","ay","az","roll","pitch","yaw",
        "pression","temperature","batterie"
    ])
    wb.save(EXCEL_FILE)

    return {"status": "ok"}

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    html_content = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FDMS Dashboard Pro - Groupe 6</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/apexcharts"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap" rel="stylesheet">

    <style>
        body { background: #f8fafc; font-family: 'Inter', sans-serif; }
        .glass-card { 
            background: white; 
            border-radius: 16px; 
            border: 1px solid #e2e8f0;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }
    #dropZone.dragover {
    border-color: #3b82f6;
    background: #eff6ff;
    color: #3b82f6;
    }
    </style>
</head>
<body class="flex h-screen p-6 gap-6">

    <aside class="w-72 glass-card p-6 flex flex-col shrink-0">
        <div class="flex items-center gap-3 mb-10 px-2">
            <div class="bg-blue-600 w-10 h-10 rounded-xl flex items-center justify-center text-white">
                <i class="fas fa-plane"></i>
            </div>
            <h1 class="text-xl font-black text-slate-800">FDMS <span class="text-blue-600">PRO</span></h1>
        </div>

        <nav class="flex-1 space-y-2">
            <a href="/" class="flex items-center gap-4 text-slate-500 hover:bg-slate-50 p-4 rounded-xl transition-all font-semibold">
                <i class="fas fa-home w-5"></i> Accueil
            </a>
            <div class="flex items-center gap-4 bg-blue-600 text-white p-4 rounded-xl font-bold shadow-lg shadow-blue-200">
                <i class="fas fa-chart-pie w-5"></i> Dashboard
            </div>
            <a href="/latest-data" target="_blank" class="flex items-center gap-4 text-slate-500 hover:bg-slate-50 p-4 rounded-xl transition-all font-semibold">
                <i class="fas fa-bolt w-5 text-amber-500"></i> Flux JSON
            </a>
            <div class="pt-4 mt-4 border-t border-slate-100 space-y-2"
            >
             <input type="file" id="fileInput" class="hidden" accept=".xlsx" onchange="handleFileUpload(event)">
            <button onclick="document.getElementById('fileInput').click()" class="w-full flex items-center gap-4 text-blue-600 hover:bg-blue-50 p-4 rounded-xl transition-all font-bold border border-blue-100">
           <i class="fas fa-file-import"></i> Import Données
                </button>
                          
                <a href="/export-excel" class="flex items-center gap-4 text-emerald-600 hover:bg-emerald-50 p-4 rounded-xl transition-all font-bold border border-emerald-100">
                    <i class="fas fa-file-csv"></i> Export Données
                </a>
                
                <button onclick="confirmDelete()" class="w-full flex items-center gap-4 text-red-600 hover:bg-red-50 p-4 rounded-xl transition-all font-bold border border-red-100">
                    <i class="fas fa-trash-alt"></i> Supprimer Data
                </button>
            </div>
        </nav>
    </aside>

    <main class="flex-1 flex flex-col gap-6 overflow-y-auto">
        
        <div class="grid grid-cols-4 gap-4">
            <div class="glass-card p-4">
                <p class="text-xs font-bold text-slate-400 uppercase">Altitude</p>
                <div class="text-2xl font-black text-slate-800"><span id="card-alt">--</span> <small class="text-slate-400 text-sm">m</small></div>
            </div>
            <div class="glass-card p-4">
                <p class="text-xs font-bold text-slate-400 uppercase">Vitesse</p>
                <div class="text-2xl font-black text-slate-800"><span id="card-vit">--</span> <small class="text-slate-400 text-sm">m/s</small></div>
            </div>
            <div class="glass-card p-4">
                <p class="text-xs font-bold text-slate-400 uppercase">Batterie</p>
                <div class="text-2xl font-black text-slate-800"><span id="card-batt">--</span> <small class="text-slate-400 text-sm">%</small></div>
            </div>
            <div class="glass-card p-4">
                <p class="text-xs font-bold text-slate-400 uppercase">Température</p>
                <div class="text-2xl font-black text-slate-800"><span id="card-temp">--</span> <small class="text-slate-400 text-sm">°C</small></div>
            </div>
        </div>
            <div id="dropZone" class="glass-card p-6 text-center border-2 border-dashed border-slate-300 text-slate-500 font-semibold">
    📂 Glissez votre fichier Excel ici ou utilisez "Import Données"
            </div>
            <input type="file" id="hiddenFileInput" style="display:none">
        <div id="charts-container" class="space-y-6">
            </div>
    </main>

    <script>
    
    console.log("Dashboard JS chargé");

// ==========================
// 📊 CHARTS CONFIG
// ==========================
const commonOptions = (colors, title) => ({
    chart: {
        type: 'line',
        height: 300,
        toolbar: { show: false },
        animations: { enabled: true }
    },
    series: [],
    colors: Array.isArray(colors) ? colors : [colors],
    stroke: { width: 3, curve: 'smooth' },
    xaxis: {
        type: 'datetime'
    },
    yaxis: {
        title: { text: title }
    },
    noData: { text: "Chargement..." }
});

const chartConfigs = [
    { id: 'altitude', color: '#3b82f6', label: 'Altitude', multi: false },
    { id: 'vitesse', color: '#f43f5e', label: 'Vitesse', multi: false },
    { id: 'pression', color: '#6366f1', label: 'Pression', multi: false },
    { id: 'temperature', color: '#f59e0b', label: 'Température', multi: false },
    { id: 'batterie', color: '#10b981', label: 'Batterie', multi: false },
    { id: 'accel', color: ['#3b82f6','#f43f5e','#10b981'], label: 'Accélération', multi: true, keys: ['ax','ay','az'] },
    { id: 'attitude', color: ['#8b5cf6','#ec4899'], label: 'Attitude', multi: true, keys: ['roll','pitch'] },
    { id: 'yaw', color: '#475569', label: 'Yaw', multi: false }
];

const charts = {};

// ==========================
// 📦 INIT CHARTS
// ==========================
const container = document.getElementById("charts-container");

chartConfigs.forEach(conf => {
    const div = document.createElement("div");
    div.className = "glass-card p-6";
    div.innerHTML = `<h3 class="font-bold mb-3">${conf.label}</h3><div id="chart-${conf.id}"></div>`;
    container.appendChild(div);

    charts[conf.id] = new ApexCharts(
        document.querySelector(`#chart-${conf.id}`),
        commonOptions(conf.color, conf.label)
    );

    charts[conf.id].render();
});

// ==========================
// 🔌 WEBSOCKET UNIQUE
// ==========================
const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
const socket = new WebSocket(`${wsProtocol}://${window.location.host}/ws`);

socket.onmessage = (event) => {
    const data = JSON.parse(event.data);

    // 🟢 CARTES
    document.getElementById("card-alt").innerText = data.altitude ?? "--";
    document.getElementById("card-vit").innerText = data.vitesse ?? "--";
    document.getElementById("card-batt").innerText = data.batterie ?? "--";
    document.getElementById("card-temp").innerText = data.temperature ?? "--";

    const point = (key) => ({
    x: Number(data.timestamp) * 1000,
    y: Number(data[key])
});

    // 📈 UPDATE GRAPHS LIVE
    chartConfigs.forEach(conf => {
        if (conf.multi) {
            charts[conf.id].appendData(
                conf.keys.map(k => ({ data: [point(k)] }))
            );
        } else {
            charts[conf.id].appendData([
                { data: [point(conf.id)] }
            ]);
        }
    });
};

socket.onerror = (err) => {
    console.error("WebSocket error:", err);
};

// ==========================
// 🔄 REFRESH INITIAL (OPTIONNEL)
// ==========================
async function refresh() {
    try {
        const res = await fetch("/graph-data");
        const data = await res.json();

        const mapData = (key) =>
            data.map(d => ({
                x: Number(d.timestamp) * 1000,
                y: Number(d[key])
            }));

        chartConfigs.forEach(conf => {
            if (conf.multi) {
                charts[conf.id].updateSeries(
                    conf.keys.map(k => ({
                        name: k,
                        data: mapData(k)
                    }))
                );
            } else {
                charts[conf.id].updateSeries([{
                    data: mapData(conf.id)
                }]);
            }
        });

    } catch (e) {
        console.error("refresh error:", e);
    }
}

// ==========================
// 🚀 START
// ==========================
window.onload = () => {
    refresh(); // chargement initial seulement
};

// ==========================
// ==========================
// 📂 UPLOAD EXCEL FUNCTION
// ==========================

async function handleFileUpload(file) {
    if (!file) return;

    if (!file.name.endsWith(".xlsx")) {
        alert("❌ Format invalide. Veuillez envoyer un fichier .xlsx");
        return;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
        const res = await fetch("/upload-excel", {
            method: "POST",
            body: formData
        });

        if (!res.ok) throw new Error("Upload failed");

        const result = await res.json();

        if (result.status === "ok") {
            alert(`✅ Import réussi : ${result.data.length} lignes`);

            if (typeof refresh === "function") {
                refresh();
            }
        } else {
            alert(result.error || "Erreur import Excel");
        }

    } catch (err) {
        console.error(err);
        alert("🚨 Erreur upload fichier");
    }
}

// ==========================
// ==========================
// 📦 DRAG & DROP
// ==========================

const dropZone = document.getElementById("dropZone");

if (dropZone) {

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("dragover");
    });

    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("dragover");
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");

        const file = e.dataTransfer.files?.[0];

        if (!file) {
            alert("❌ Aucun fichier détecté");
            return;
        }

        handleFileUpload(file);
    });
}

</script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)
