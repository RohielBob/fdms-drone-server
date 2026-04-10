import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from openpyxl import Workbook, load_workbook

from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials, db

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

excel_lock = threading.Lock()

# =====================================================
# FIREBASE
# =====================================================
FIREBASE_DB_URL = "https://drone-fdm-project-groupe-6-default-rtdb.firebaseio.com/"
firebase_enabled = False

if os.path.exists(FIREBASE_CREDENTIALS):
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(FIREBASE_CREDENTIALS)
            firebase_admin.initialize_app(cred, {
                "databaseURL": FIREBASE_DB_URL
            })
        firebase_enabled = True
    except Exception as e:
        print("Erreur Firebase :", e)
        firebase_enabled = False
else:
    print("firebase_key.json introuvable")

# =====================================================
# MODELE (FIX 422 ICI)
# =====================================================
class DroneData(BaseModel):
    Flight_ID: Optional[str] = "MISSION"
    Date: Optional[str] = None
    timestamp: int

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

    batterie: Optional[float] = 100.0


# =====================================================
# EXCEL INIT
# =====================================================
if not os.path.exists(EXCEL_FILE):
    wb = Workbook()
    ws = wb.active
    ws.title = "Données Drone"
    ws.append([
        "Flight_ID","Date","timestamp","altitude","vitesse",
        "ax","ay","az","roll","pitch","yaw",
        "pression","temperature","batterie"
    ])
    wb.save(EXCEL_FILE)

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
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn


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
    return "<h1>FDMS SERVER OK 🚀</h1>"


# =====================================================
# POST DRONE DATA (MISSION PLANNER SAFE)
# =====================================================
@app.post("/drone-data")
def receive_drone_data(data: DroneData):

    data_dict = data.dict()

    # sécurité batterie (évite crash)
    if data_dict.get("batterie") is None:
        data_dict["batterie"] = 100.0

    alerts = generate_alerts(data_dict)

    # =========================
    # SQLITE
    # =========================
    conn = get_db_connection()
    cursor = conn.cursor()

    # === DANS TON CODE SERVEUR ===
    cursor.execute("""
        INSERT INTO drone_data (
            Flight_ID, Date, timestamp, altitude, vitesse,
            ax, ay, az, roll, pitch, yaw,
            pression, temperature, batterie
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ( # Il doit y avoir EXACTEMENT 14 points d'interrogation ci-dessus
        data.Flight_ID,
        data.Date,
        data.timestamp,
        data.altitude,
        data.vitesse,
        data.ax,
        data.ay,
        data.az,
        data.roll,
        data.pitch,
        data.yaw,
        data.pression,
        data.temperature,
        data.batterie
    ))

    conn.commit()
    conn.close()

    # =========================
    # EXCEL
    # =========================
    try:
        with excel_lock:
            wb = load_workbook(EXCEL_FILE)
            ws = wb.active

            ws.append([
                data.Flight_ID,
                data.Date,
                data.timestamp,
                data.altitude,
                data.vitesse,
                data.ax,
                data.ay,
                data.az,
                data.roll,
                data.pitch,
                data.yaw,
                data.pression,
                data.temperature,
                data.batterie
            ])

            wb.save(EXCEL_FILE)
    except:
        pass

    # =========================
    # FIREBASE
    # =========================
    if firebase_enabled:
        try:
            db.reference("drone_data").push(data_dict)
        except:
            pass

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


# =====================================================
# GRAPH DATA
# =====================================================
@app.get("/graph-data")
def graph_data():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM drone_data ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


# =====================================================
# EXPORT EXCEL
# =====================================================
@app.get("/export-excel")
def export_excel():
    return FileResponse(EXCEL_FILE)


# =====================================================
# RESET DATA
# =====================================================
@app.delete("/reset-data")
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
    return """
    <html>
    <head>
        <title>FDMS AI Dashboard</title>
        <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>

        <style>
            body {
                margin: 0;
                font-family: 'Inter', sans-serif;
                background: #0f172a;
                color: white;
                display: flex;
            }

            /* SIDEBAR */
            .sidebar {
                width: 250px;
                background: #020617;
                height: 100vh;
                padding: 20px;
                border-right: 1px solid #1e293b;
            }

            .sidebar h2 {
                margin-bottom: 30px;
                color: #38bdf8;
            }

            .sidebar a {
                display: block;
                padding: 12px;
                margin-bottom: 10px;
                border-radius: 10px;
                color: #94a3b8;
                text-decoration: none;
                transition: 0.2s;
            }

            .sidebar a:hover {
                background: #1e293b;
                color: white;
            }

            /* MAIN */
            .main {
                flex: 1;
                padding: 20px;
            }

            .topbar {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 25px;
            }

            .status {
                background: #022c22;
                padding: 6px 14px;
                border-radius: 999px;
                color: #4ade80;
                font-size: 14px;
            }

            /* KPI CARDS */
            .cards {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px,1fr));
                gap: 20px;
                margin-bottom: 25px;
            }

            .card {
                background: linear-gradient(145deg, #1e293b, #0f172a);
                padding: 20px;
                border-radius: 16px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.4);
                transition: 0.3s;
            }

            .card:hover {
                transform: translateY(-5px);
            }

            .card h4 {
                color: #94a3b8;
                margin: 0;
            }

            .card h2 {
                margin: 5px 0 0;
                font-size: 26px;
            }

            /* GRID GRAPHS */
            .grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(400px,1fr));
                gap: 20px;
            }

            .graph {
                background: #020617;
                border-radius: 16px;
                padding: 15px;
                box-shadow: 0 8px 20px rgba(0,0,0,0.4);
            }

        </style>
    </head>

    <body>

        <div class="sidebar">
            <h2>🚁 FDMS AI</h2>
            <a href="/dashboard">Dashboard</a>
            <a href="/docs">API</a>
            <a href="/latest-data">Latest</a>
            <a href="/all-data">All Data</a>
        </div>

        <div class="main">

            <div class="topbar">
                <h1>Drone Intelligence</h1>
                <div class="status">● LIVE</div>
            </div>

            <div class="cards">
                <div class="card"><h4>Altitude</h4><h2 id="altitude">--</h2></div>
                <div class="card"><h4>Vitesse</h4><h2 id="vitesse">--</h2></div>
                <div class="card"><h4>Température</h4><h2 id="temperature">--</h2></div>
                <div class="card"><h4>Pression</h4><h2 id="pression">--</h2></div>
                <div class="card"><h4>Batterie</h4><h2 id="batterie">--</h2></div>
            </div>

            <div class="grid">
                <div class="graph"><div id="altitude_chart"></div></div>
                <div class="graph"><div id="vitesse_chart"></div></div>
                <div class="graph"><div id="temperature_chart"></div></div>
                <div class="graph"><div id="pression_chart"></div></div>
                <div class="graph"><div id="roll_chart"></div></div>
                <div class="graph"><div id="pitch_chart"></div></div>
            </div>

        </div>

    <script>

    async function updateData(){
        const res = await fetch('/graph-data');
        const data = await res.json();

        if(!data || data.length === 0) return;

        const t = data.map(d=>d.Date);

        function plot(id, values, title){
            Plotly.react(id, [{
                x: t,
                y: values,
                mode: 'lines',
                line: {shape: 'spline'}
            }], {
                title: title,
                paper_bgcolor:"#020617",
                plot_bgcolor:"#020617",
                font:{color:"white"}
            });
        }

        plot("altitude_chart", data.map(d=>d.altitude), "Altitude");
        plot("vitesse_chart", data.map(d=>d.vitesse), "Vitesse");
        plot("temperature_chart", data.map(d=>d.temperature), "Température");
        plot("pression_chart", data.map(d=>d.pression), "Pression");
        plot("roll_chart", data.map(d=>d.roll), "Roll");
        plot("pitch_chart", data.map(d=>d.pitch), "Pitch");

        const last = data[data.length-1];

        document.getElementById("altitude").innerText = last.altitude;
        document.getElementById("vitesse").innerText = last.vitesse;
        document.getElementById("temperature").innerText = last.temperature;
        document.getElementById("pression").innerText = last.pression;
        document.getElementById("batterie").innerText = last.batterie || "--";
    }

    updateData();
    setInterval(updateData, 1000);

    </script>

    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
