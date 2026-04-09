import os
import sqlite3
import threading
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from openpyxl import Workbook, load_workbook

# CORS
from fastapi.middleware.cors import CORSMiddleware

# Firebase
import firebase_admin
from firebase_admin import credentials, db

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

# -----------------------------
# Configuration Firebase
# -----------------------------

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
        print("Erreur Firebase au démarrage :", e)
        firebase_enabled = False
else:
    print("firebase_key.json introuvable : Firebase désactivé")

# -----------------------------
# Modèle de données du drone
# -----------------------------
class DroneData(BaseModel):
    temperature: float
    altitude: float
    vitesse: float
    batterie: float
    roll: float
    pitch: float
    yaw: float

# -----------------------------
# Fichiers de stockage
# -----------------------------


# -----------------------------
# Création fichier Excel si absent
# -----------------------------
if not os.path.exists(EXCEL_FILE):
    wb = Workbook()
    ws = wb.active
    ws.title = "Données Drone"
    ws.append([
        "timestamp",
        "temperature",
        "altitude",
        "vitesse",
        "batterie",
        "roll",
        "pitch",
        "yaw"
    ])
    wb.save(EXCEL_FILE)

# -----------------------------
# Initialisation SQLite
# -----------------------------
def init_db():
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drone_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            temperature REAL,
            altitude REAL,
            vitesse REAL,
            batterie REAL,
            roll REAL,
            pitch REAL,
            yaw REAL
        )
    """)

    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn

# -----------------------------
# Fonction utilitaire : alertes
# -----------------------------
def generate_alerts(data_dict):
    alerts = []

    if data_dict["temperature"] < -50 or data_dict["temperature"] > 150:
        alerts.append("Température inhabituelle")

    if data_dict["altitude"] < -100 or data_dict["altitude"] > 10000:
        alerts.append("Altitude inhabituelle")

    if data_dict["vitesse"] < 0 or data_dict["vitesse"] > 300:
        alerts.append("Vitesse inhabituelle")

    if data_dict["batterie"] < 0 or data_dict["batterie"] > 30:
        alerts.append("Valeur batterie inhabituelle")

    if data_dict["roll"] < -180 or data_dict["roll"] > 180:
        alerts.append("Roll inhabituel")

    if data_dict["pitch"] < -180 or data_dict["pitch"] > 180:
        alerts.append("Pitch inhabituel")

    if data_dict["yaw"] < -360 or data_dict["yaw"] > 360:
        alerts.append("Yaw inhabituel")

    return alerts

# -----------------------------
# Page d’accueil
# -----------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <html>
        <head>
            <title>FDMS Control Center</title>
            <meta charset="UTF-8">
            <style>
                body {
                    margin: 0;
                    font-family: Arial, sans-serif;
                    background: #f5f7fb;
                    color: #111827;
                }

                .topbar {
                    background: linear-gradient(135deg, #0f172a, #1e293b);
                    color: white;
                    padding: 40px 20px;
                    text-align: center;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.2);
                }

                .topbar h1 {
                    margin: 0;
                    font-size: 42px;
                    font-weight: bold;
                }

                .topbar p {
                    margin-top: 12px;
                    font-size: 18px;
                    opacity: 0.9;
                }

                .container {
                    max-width: 1250px;
                    margin: 35px auto;
                    padding: 20px;
                }

                .status-row {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                    gap: 20px;
                    margin-bottom: 35px;
                }

                .status-card {
                    background: white;
                    border-radius: 18px;
                    padding: 22px;
                    box-shadow: 0 6px 18px rgba(0,0,0,0.08);
                    transition: 0.2s ease;
                }

                .status-card:hover {
                    transform: translateY(-4px);
                    box-shadow: 0 10px 22px rgba(0,0,0,0.12);
                }

                .status-card h3 {
                    margin: 0 0 10px 0;
                    font-size: 18px;
                    color: #374151;
                }

                .status-card .value {
                    font-size: 28px;
                    font-weight: bold;
                    color: #111827;
                }

                .green {
                    color: #16a34a;
                }

                .section-title {
                    font-size: 30px;
                    margin: 30px 0 20px;
                    text-align: center;
                    color: #111827;
                }

                .grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
                    gap: 22px;
                }

                .card {
                    background: white;
                    border-radius: 20px;
                    padding: 25px;
                    box-shadow: 0 6px 18px rgba(0,0,0,0.08);
                    transition: transform 0.2s ease, box-shadow 0.2s ease;
                    position: relative;
                    overflow: hidden;
                }

                .card:hover {
                    transform: translateY(-6px);
                    box-shadow: 0 12px 26px rgba(0,0,0,0.12);
                }

                .card h3 {
                    margin-top: 0;
                    font-size: 23px;
                    color: #111827;
                }

                .card p {
                    font-size: 15px;
                    color: #4b5563;
                    line-height: 1.6;
                }

                .btn {
                    display: inline-block;
                    margin-top: 16px;
                    padding: 11px 18px;
                    background: #111827;
                    color: white;
                    text-decoration: none;
                    border-radius: 12px;
                    font-weight: bold;
                    transition: 0.2s ease;
                }

                .btn:hover {
                    background: #2563eb;
                }

                .hero-panel {
                    background: white;
                    border-radius: 22px;
                    padding: 28px;
                    margin-bottom: 35px;
                    box-shadow: 0 6px 18px rgba(0,0,0,0.08);
                }

                .hero-panel h2 {
                    margin-top: 0;
                    font-size: 30px;
                    color: #111827;
                }

                .hero-panel p {
                    color: #4b5563;
                    font-size: 16px;
                    line-height: 1.7;
                }

                .live-box {
                    background: #f9fafb;
                    border: 1px solid #e5e7eb;
                    border-radius: 16px;
                    padding: 18px;
                    margin-top: 20px;
                }

                .live-box h4 {
                    margin-top: 0;
                    margin-bottom: 10px;
                    color: #111827;
                }

                .live-box pre {
                    white-space: pre-wrap;
                    word-wrap: break-word;
                    font-size: 14px;
                    color: #1f2937;
                    margin: 0;
                }

                .footer {
                    text-align: center;
                    padding: 30px 20px;
                    color: #6b7280;
                    font-size: 14px;
                    margin-top: 40px;
                }

                .badge {
                    display: inline-block;
                    background: #dcfce7;
                    color: #166534;
                    padding: 8px 14px;
                    border-radius: 999px;
                    font-size: 14px;
                    font-weight: bold;
                    margin-top: 12px;
                }
            </style>
        </head>
        <body>

            <div class="topbar">
                <h1>FDMS Control Center</h1>
                <p>Flight Data Monitoring System - Interface centrale du serveur du drone</p>
                <div class="badge">Système en ligne</div>
            </div>

            <div class="container">

                <div class="hero-panel">
                    <h2>Bienvenue sur le serveur FDMS du groupe 6</h2>
                    <p>
                        Cette interface vous permet d’accéder rapidement à toutes les fonctionnalités principales
                        du système de surveillance de vol du drone : réception des données, visualisation,
                        monitoring en temps réel, consultation des historiques, documentation API, accès au dashboard
                        et consultation directe des données stockées dans Firebase.
                    </p>

                    <div class="live-box">
                        <h4>📡 Dernières données reçues (temps réel)</h4>
                        <pre id="latestData">Chargement...</pre>
                    </div>
                </div>

                <div class="status-row">
                    <div class="status-card">
                        <h3>🟢 Statut du serveur</h3>
                        <div class="value green">Actif</div>
                    </div>

                    <div class="status-card">
                        <h3>🕒 Heure actuelle</h3>
                        <div class="value" id="clock">--:--:--</div>
                    </div>

                    <div class="status-card">
                        <h3>📦 Données reçues</h3>
                        <div class="value" id="totalData">...</div>
                    </div>

                    <div class="status-card">
                        <h3>🌐 Mode d’accès</h3>
                        <div class="value">Local / Public</div>
                    </div>
                </div>

                <h2 class="section-title">Accès rapide</h2>

                <div class="grid">
                    <div class="card">
                        <h3>📊 Dashboard</h3>
                        <p>Visualiser les graphiques de vol du drone : altitude, température, vitesse, batterie, roll, pitch et yaw.</p>
                        <a class="btn" href="/dashboard">Ouvrir Dashboard</a>
                    </div>

                    <div class="card">
                        <h3>🧾 Documentation API</h3>
                        <p>Accéder à l’interface Swagger de FastAPI pour tester toutes les routes de ton serveur.</p>
                        <a class="btn" href="/docs">Ouvrir Docs</a>
                    </div>

                    <div class="card">
                        <h3>📍 Latest Data</h3>
                        <p>Afficher uniquement la dernière donnée reçue du drone en temps réel.</p>
                        <a class="btn" href="/latest-data">Voir Latest Data</a>
                    </div>

                    <div class="card">
                        <h3>📚 All Data</h3>
                        <p>Afficher toutes les données du drone actuellement enregistrées par le serveur.</p>
                        <a class="btn" href="/all-data">Voir All Data</a>
                    </div>

                    <div class="card">
                        <h3>📡 Réception Drone</h3>
                        <p>Point d’entrée API utilisé pour recevoir les données du drone.</p>
                        <a class="btn" href="/docs#/default/receive_drone_data_drone_data_post">Tester Drone Data</a>
                    </div>

                    <div class="card">
                        <h3>☁️ Firebase</h3>
                        <p>Consulter directement la base de données temps réel stockée sur Firebase Realtime Database.</p>
                        <a class="btn" href="https://console.firebase.google.com/u/0/project/drone-fdm-project-groupe-6/database/drone-fdm-project-groupe-6-default-rtdb/data" target="_blank">Ouvrir Firebase</a>
                    </div>

                    <div class="card">
                        <h3>📥 Export Excel</h3>
                        <p>Télécharger l’ensemble des données collectées au format Excel pour archivage ou traitement externe.</p>
                        <a class="btn" href="/export-excel">Télécharger Excel</a>
                    </div>

                    <div class="card">
                        <h3>🩺 Health Check</h3>
                        <p>Afficher l’état technique du système : stockage, base SQLite, Firebase et dernière réception.</p>
                        <a class="btn" href="/health">Voir Health</a>
                    </div>
                    
                    <div class="card">
                        <h3>🗑 Réinitialiser les données</h3>
                        <p>Supprimer toutes les données du drone enregistrées dans (SQLite + Excel).</p>
                        <a class="btn" onclick="resetData()">Réinitialiser</a>
                    </div>
                </div>
            </div>

            <div class="footer">
                FDMS Drone Project • Groupe 6 • Serveur Python FastAPI + Dashboard + Firebase
            </div>

            <script>
                function updateClock() {
                    const now = new Date();
                    document.getElementById("clock").textContent = now.toLocaleTimeString();
                }

                async function updateLatestData() {
                    try {
                        const response = await fetch('/latest-data');
                        const data = await response.json();
                        document.getElementById("latestData").textContent = JSON.stringify(data, null, 2);
                    } catch (error) {
                        document.getElementById("latestData").textContent = "Impossible de charger les données.";
                    }
                }

                async function updateTotalData() {
                    try {
                        const response = await fetch('/summary');
                        const data = await response.json();

                        if (data && !data.error) {
                            document.getElementById("totalData").textContent = data.total_points;
                        } else {
                            document.getElementById("totalData").textContent = "0";
                        }
                    } catch (error) {
                        document.getElementById("totalData").textContent = "Erreur";
                    }
                }
                
                async function resetData() {
                    const confirmation = confirm("Voulez-vous vraiment supprimer toutes les données du drone ?");
    
                    if (!confirmation) return;

                    try {
                    const response = await fetch('/reset-data', {
            method: 'DELETE'
        });

                   const result = await response.json();

                 if (result.status === "ok") {
                   alert("Données réinitialisées avec succès !");
                   location.reload();
                } else {
            alert("Erreur : " + (result.error || "Impossible de réinitialiser"));
        }
    } catch (error) {
        alert("Erreur serveur lors de la réinitialisation");
        console.error(error);
    }
}

                
                updateClock();
                updateLatestData();
                updateTotalData();

                setInterval(updateClock, 1000);
                setInterval(updateLatestData, 3000);
                setInterval(updateTotalData, 3000);
            </script>

        </body>
    </html>
    """

# -----------------------------
# Reset des données
# -----------------------------
@app.delete("/reset-data")
def reset_data():
    try:
        conn = sqlite3.connect(SQLITE_DB)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM drone_data")
        conn.commit()
        conn.close()

        with excel_lock:
            wb = Workbook()
            ws = wb.active
            ws.title = "Données Drone"
            ws.append([
                "timestamp",
                "temperature",
                "altitude",
                "vitesse",
                "batterie",
                "roll",
                "pitch",
                "yaw"
            ])
            wb.save(EXCEL_FILE)

        return {"status": "ok", "message": "Toutes les données ont été réinitialisées"}

    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Réception des données du drone
# -----------------------------
@app.post("/drone-data")
def receive_drone_data(data: DroneData):
    print("Données reçues :", data)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    alerts = []

    if data.temperature < -50 or data.temperature > 150:
        alerts.append("Température inhabituelle")

    if data.altitude < -100 or data.altitude > 10000:
        alerts.append("Altitude inhabituelle")

    if data.vitesse < 0 or data.vitesse > 300:
        alerts.append("Vitesse inhabituelle")

    if data.batterie < 0 or data.batterie > 30:
        alerts.append("Valeur batterie inhabituelle")

    if data.roll < -180 or data.roll > 180:
        alerts.append("Roll inhabituel")

    if data.pitch < -180 or data.pitch > 180:
        alerts.append("Pitch inhabituel")

    if data.yaw < -360 or data.yaw > 360:
        alerts.append("Yaw inhabituel")

    # 1) Excel
    try:
        with excel_lock:
            wb = load_workbook(EXCEL_FILE)
            ws = wb.active
            ws.append([
                timestamp,
                data.temperature,
                data.altitude,
                data.vitesse,
                data.batterie,
                data.roll,
                data.pitch,
                data.yaw
            ])
            wb.save(EXCEL_FILE)
        excel_status = "ok"
    except PermissionError:
        excel_status = "erreur : fichier Excel ouvert ou bloqué"
    except Exception as e:
        excel_status = f"erreur Excel : {str(e)}"

    # 2) SQLite
    try:
        conn = sqlite3.connect(SQLITE_DB)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO drone_data (
                timestamp, temperature, altitude, vitesse, batterie, roll, pitch, yaw
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp,
            data.temperature,
            data.altitude,
            data.vitesse,
            data.batterie,
            data.roll,
            data.pitch,
            data.yaw
        ))

        conn.commit()
        conn.close()
        sqlite_status = "ok"
    except Exception as e:
        sqlite_status = f"erreur SQLite : {str(e)}"

    # 3) Firebase
    try:
        if firebase_enabled:
            drone_ref = db.reference("drone_data")
            drone_ref.push({
                "timestamp": timestamp,
                "temperature": data.temperature,
                "altitude": data.altitude,
                "vitesse": data.vitesse,
                "batterie": data.batterie,
                "roll": data.roll,
                "pitch": data.pitch,
                "yaw": data.yaw
            })
            firebase_status = "ok"
        else:
            firebase_status = "désactivé"
    except Exception as e:
        firebase_status = f"erreur Firebase : {str(e)}"

    return {
        "status": "succès",
        "message": "Données reçues et traitées",
        "excel_status": excel_status,
        "sqlite_status": sqlite_status,
        "firebase_status": firebase_status,
        "data": data,
        "alerts": alerts
    }
# -----------------------------
# Dernière donnée
# -----------------------------
@app.get("/latest-data")
def latest_data():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT timestamp, temperature, altitude, vitesse, batterie, roll, pitch, yaw
            FROM drone_data
            ORDER BY id DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return {"message": "Aucune donnée disponible"}

        data = dict(row)
        data["alerts"] = generate_alerts(data)
        return data

    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Toutes les données
# -----------------------------
@app.get("/all-data")
def all_data():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT timestamp, temperature, altitude, vitesse, batterie, roll, pitch, yaw
            FROM drone_data
            ORDER BY id ASC
        """)
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    except Exception as e:
        return {"error": str(e)}

@app.get("/all-data-sql")
def all_data_sql():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM drone_data ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    except Exception as e:
        return {"error": str(e)}

@app.get("/latest-data-sql")
def latest_data_sql():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM drone_data ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return {"message": "Aucune donnée disponible"}

        return dict(row)

    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Santé du système
# -----------------------------
@app.get("/health")
def health():
    try:
        excel_exists = os.path.exists(EXCEL_FILE)
        sqlite_exists = os.path.exists(SQLITE_DB)

        total_data = 0
        last_timestamp = "aucune donnée"

        if sqlite_exists:
            conn = sqlite3.connect(SQLITE_DB)
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM drone_data")
            total_data = cursor.fetchone()[0]

            cursor.execute("SELECT timestamp FROM drone_data ORDER BY id DESC LIMIT 1")
            last_row = cursor.fetchone()

            if last_row:
                last_timestamp = last_row[0]

            conn.close()

        return {
            "status": "ok",
            "server": "FDMS",
            "firebase": "actif" if firebase_enabled else "désactivé",
            "excel": "présent" if excel_exists else "absent",
            "sqlite": "présent" if sqlite_exists else "absent",
            "nombre_donnees": total_data,
            "derniere_reception": last_timestamp,
            "mode_stockage": "SQLite + Excel + Firebase"
        }

    except Exception as e:
        return {
            "status": "erreur",
            "server": "FDMS",
            "details": str(e)
        }

# -----------------------------
# Résumé mission
# -----------------------------
@app.get("/summary")
def summary():
    try:
        conn = sqlite3.connect(SQLITE_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                COUNT(*) as total_points,
                MAX(altitude) as max_altitude,
                MAX(vitesse) as max_vitesse,
                AVG(temperature) as avg_temp
            FROM drone_data
        """)
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return {
                "total_points": 0,
                "max_altitude": 0,
                "max_vitesse": 0,
                "avg_temp": 0
            }

        return {
            "total_points": row[0] if row[0] is not None else 0,
            "max_altitude": round(row[1], 2) if row[1] is not None else 0,
            "max_vitesse": round(row[2], 2) if row[2] is not None else 0,
            "avg_temp": round(row[3], 2) if row[3] is not None else 0
        }

    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Données graphiques
# -----------------------------
@app.get("/graph-data")
def graph_data(limit: int = 0):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if limit > 0:
            cursor.execute("""
                SELECT timestamp, temperature, altitude, vitesse, batterie, roll, pitch, yaw
                FROM drone_data
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            rows = list(reversed(rows))
        else:
            cursor.execute("""
                SELECT timestamp, temperature, altitude, vitesse, batterie, roll, pitch, yaw
                FROM drone_data
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()

        conn.close()
        return [dict(row) for row in rows]

    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Export Excel
# -----------------------------
@app.get("/export-excel")
def export_excel():
    try:
        if os.path.exists(EXCEL_FILE):
            return FileResponse(
                path=EXCEL_FILE,
                filename="drone_data.xlsx",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            return {"error": "Fichier Excel introuvable"}

    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Dashboard
# -----------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    html_content = """
    <html>
        <head>
            <title>FDMS Dashboard du groupe 6</title>
            <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
            <style>
                * {
                    box-sizing: border-box;
                }

                body {
                    margin: 0;
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #f4f6f9;
                    color: #0f172a;
                }

                .header {
                    background: linear-gradient(90deg, #0f172a, #1e293b);
                    padding: 30px 40px;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.20);
                }

                .header-top {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    flex-wrap: wrap;
                    gap: 15px;
                }

                .title {
                    font-size: 34px;
                    font-weight: 800;
                    color: white;
                }

                .subtitle {
                    margin-top: 8px;
                    color: #cbd5e1;
                    font-size: 15px;
                }

                .status {
                    background: rgba(34,197,94,0.15);
                    border: 1px solid rgba(34,197,94,0.35);
                    color: #22c55e;
                    padding: 12px 18px;
                    border-radius: 999px;
                    font-weight: 600;
                }

                .container {
                    padding: 30px;
                }

                .section-title {
                    font-size: 24px;
                    font-weight: 700;
                    margin-bottom: 20px;
                    color: #0f172a;
                }

                .cards {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                    gap: 20px;
                    margin-bottom: 35px;
                }

                .card {
                    background: white;
                    border: 1px solid #e2e8f0;
                    border-radius: 22px;
                    padding: 22px;
                    box-shadow: 0 8px 20px rgba(0,0,0,0.06);
                    transition: transform 0.25s ease, box-shadow 0.25s ease;
                }

                .card:hover {
                    transform: translateY(-4px);
                    box-shadow: 0 12px 25px rgba(0,0,0,0.10);
                }

                .card-label {
                    font-size: 14px;
                    color: #64748b;
                    margin-bottom: 12px;
                    text-transform: uppercase;
                    letter-spacing: 0.8px;
                }

                .card-value {
                    font-size: 30px;
                    font-weight: 800;
                    color: #0f172a;
                }

                .card-sub {
                    margin-top: 8px;
                    font-size: 13px;
                    color: #94a3b8;
                }

                .stats-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                    gap: 20px;
                    margin-bottom: 40px;
                }

                .graph {
                    background: white;
                    border: 1px solid #e2e8f0;
                    border-radius: 24px;
                    padding: 20px;
                    box-shadow: 0 8px 20px rgba(0,0,0,0.06);
                    margin-bottom: 30px;
                }

                .footer-note {
                    margin-top: 40px;
                    text-align: center;
                    color: #64748b;
                    font-size: 13px;
                }

                .live-indicator {
                    display: inline-flex;
                    align-items: center;
                    gap: 8px;
                }

                .dot {
                    width: 10px;
                    height: 10px;
                    background: #22c55e;
                    border-radius: 50%;
                    box-shadow: 0 0 12px #22c55e;
                    animation: pulse 1.5s infinite;
                }

                @keyframes pulse {
                    0% { transform: scale(1); opacity: 1; }
                    50% { transform: scale(1.4); opacity: 0.6; }
                    100% { transform: scale(1); opacity: 1; }
                }

                @media (max-width: 768px) {
                    .title {
                        font-size: 26px;
                    }
                }
            </style>
        </head>
        <body>
            <div class="header">
                <div class="header-top">
                    <div>
                        <div class="title">🚁 FDMS CONTROL CENTER</div>
                        <div class="subtitle">Surveillance et analyse en temps réel du drone — Groupe 6</div>
                    </div>
                    <div class="status">
                        <span class="live-indicator">
                            <span class="dot"></span>
                            Système Actif
                        </span>
                    </div>
                </div>
            </div>

            <div class="container">

                <div class="section-title">📡 État du drone en Temps Réel</div>
                <div class="cards">
                    <div class="card">
                        <div class="card-label">🌡 Température</div>
                        <div class="card-value" id="temperature">-- °C</div>
                        <div class="card-sub">Dernière donnée reçue</div>
                    </div>

                    <div class="card">
                        <div class="card-label">📏 Altitude</div>
                        <div class="card-value" id="altitude">-- m</div>
                        <div class="card-sub">Position verticale actuelle</div>
                    </div>

                    <div class="card">
                        <div class="card-label">⚡ Vitesse</div>
                        <div class="card-value" id="vitesse">-- m/s</div>
                        <div class="card-sub">Vitesse instantanée</div>
                    </div>

                    <div class="card">
                        <div class="card-label">🔋 Batterie</div>
                        <div class="card-value" id="batterie">-- V</div>
                        <div class="card-sub">Tension actuelle</div>
                    </div>

                    <div class="card">
                        <div class="card-label">🚨 Alertes</div>
                        <div class="card-value" id="alerts" style="font-size:18px;">Aucune</div>
                        <div class="card-sub">Anomalies détectées</div>
                    </div>
                </div>

                <div class="section-title">Résumé de la Mission</div>
                <div class="stats-grid">
                    <div class="card">
                        <div class="card-label">📥 Données reçues</div>
                        <div class="card-value" id="total_points">--</div>
                        <div class="card-sub">Nombre total d’échantillons</div>
                    </div>

                    <div class="card">
                        <div class="card-label">🛰 Altitude max</div>
                        <div class="card-value" id="max_altitude">-- m</div>
                        <div class="card-sub">Altitude maximale enregistrée</div>
                    </div>

                    <div class="card">
                        <div class="card-label">🚀 Vitesse max</div>
                        <div class="card-value" id="max_vitesse">-- m/s</div>
                        <div class="card-sub">Vitesse maximale enregistrée</div>
                    </div>

                    <div class="card">
                        <div class="card-label">🌡 Température moyenne</div>
                        <div class="card-value" id="avg_temp">-- °C</div>
                        <div class="card-sub">Valeur moyenne calculée</div>
                    </div>
                </div>

                <div class="section-title">📊 Visualisation des Paramètres de Vol</div>

                <div class="graph"><div id="altitude_chart"></div></div>
                <div class="graph"><div id="temperature_chart"></div></div>
                <div class="graph"><div id="vitesse_chart"></div></div>
                <div class="graph"><div id="batterie_chart"></div></div>
                <div class="graph"><div id="roll_chart"></div></div>
                <div class="graph"><div id="pitch_chart"></div></div>
                <div class="graph"><div id="yaw_chart"></div></div>

                <div class="footer-note">
                    •• Développé par le Groupe 6 ••
                </div>
            </div>

            <script>
    async function updateLatestCards() {
        try {
            const response = await fetch('/latest-data');
            const data = await response.json();

            if (!data || data.error || data.message) return;

            document.getElementById('temperature').innerText = data.temperature + " °C";
            document.getElementById('altitude').innerText = data.altitude + " m";
            document.getElementById('vitesse').innerText = data.vitesse + " m/s";

            let batteryText = data.batterie + " V";

            if (data.batterie < 8) {
                batteryText += " 🔴 Critique";
            } else if (data.batterie < 10) {
                batteryText += " ⚠️ Faible";
            } else {
                batteryText += " ✅ Normal";
            }

            document.getElementById('batterie').innerText = batteryText;

        } catch (error) {
            console.error("Erreur mise à jour cartes :", error);
        }
    }

    async function updateSummary() {
        try {
            const response = await fetch('/summary');
            const data = await response.json();

            if (!data || data.error) return;

            document.getElementById('total_points').innerText = data.total_points;
            document.getElementById('max_altitude').innerText = data.max_altitude + " m";
            document.getElementById('max_vitesse').innerText = data.max_vitesse + " m/s";
            document.getElementById('avg_temp').innerText = data.avg_temp + " °C";

        } catch (error) {
            console.error("Erreur résumé mission :", error);
        }
    }

    async function loadGraphs() {
        try {
            const response = await fetch('/graph-data');
            const data = await response.json();

            if (!data || data.length === 0 || data.error) return;

            const timestamps = data.map(d => d.timestamp);
            const temperature = data.map(d => d.temperature);
            const altitude = data.map(d => d.altitude);
            const vitesse = data.map(d => d.vitesse);
            const batterie = data.map(d => d.batterie);
            const roll = data.map(d => d.roll);
            const pitch = data.map(d => d.pitch);
            const yaw = data.map(d => d.yaw);

            const layout = {
                template: "plotly_white",
                height: 400,
                margin: { l: 40, r: 40, t: 60, b: 40 },
                uirevision: "fdms-dashboard"
            };

            Plotly.react('altitude_chart', [{
                x: timestamps, y: altitude, mode: 'lines+markers', name: 'Altitude'
            }], { ...layout, title: 'Altitude du drone' });

            Plotly.react('temperature_chart', [{
                x: timestamps, y: temperature, mode: 'lines+markers', name: 'Température'
            }], { ...layout, title: 'Température du drone' });

            Plotly.react('vitesse_chart', [{
                x: timestamps, y: vitesse, mode: 'lines+markers', name: 'Vitesse'
            }], { ...layout, title: 'Vitesse du drone' });

            Plotly.react('batterie_chart', [{
                x: timestamps, y: batterie, mode: 'lines+markers', name: 'Batterie'
            }], { ...layout, title: 'Tension batterie' });

            Plotly.react('roll_chart', [{
                x: timestamps, y: roll, mode: 'lines+markers', name: 'Roll'
            }], { ...layout, title: 'Roll' });

            Plotly.react('pitch_chart', [{
                x: timestamps, y: pitch, mode: 'lines+markers', name: 'Pitch'
            }], { ...layout, title: 'Pitch' });

            Plotly.react('yaw_chart', [{
                x: timestamps, y: yaw, mode: 'lines+markers', name: 'Yaw'
            }], { ...layout, title: 'Yaw' });

        } catch (error) {
            console.error("Erreur graphiques :", error);
        }
    }

    // Chargement initial
    updateLatestCards();
    updateSummary();
    loadGraphs();

    // Mise à jour en temps réel
    setInterval(updateLatestCards, 3000);
    setInterval(updateSummary, 5000);
    setInterval(loadGraphs, 5000);
</script>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)