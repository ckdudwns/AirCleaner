import requests
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timezone, timedelta
import threading
import urllib.parse
import time
import traceback

app = Flask(__name__)
CORS(app)

# ✅ KST (Korea Standard Time)
KST = timezone(timedelta(hours=9))

# ✅ 외부 API 설정 (동국 API)
DONGUK_SPEED_URL = "http://144.24.86.225:8083/dongukSpeed"  # ✅
DONGUK_KEY = "6AhrGb8HFc7sNmg3B3hY8Fo3QvNa6HxoMG2K1YsbyAqagQ2Un5x3HTkuyt13pKD7n6vVFKZBjr2Fni4ZJBQyogKM8Htamtrb4y5H"  # ✅

# ✅ DB 연결 설정
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:ckdudwns%40%401@127.0.0.1:3306/environmental_monitoring'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ===================== DB 모델 =====================
class SensorData(db.Model):
    __tablename__ = 'sensor_data'
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    temperature = db.Column(db.Numeric(5, 2))
    humidity = db.Column(db.Numeric(5, 2))
    co2eq = db.Column(db.Integer)
    tvoc = db.Column(db.Numeric(10, 3))
    pm1_0 = db.Column(db.Numeric(8, 3))
    pm2_5 = db.Column(db.Numeric(8, 3))
    pm10 = db.Column(db.Numeric(8, 3))
    measured_at = db.Column(db.TIMESTAMP, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "temperature": float(self.temperature) if self.temperature else None,
            "humidity": float(self.humidity) if self.humidity else None,
            "co2eq": self.co2eq,
            "tvoc": float(self.tvoc) if self.tvoc else None,
            "pm1_0": float(self.pm1_0) if self.pm1_0 else None,
            "pm2_5": float(self.pm2_5) if self.pm2_5 else None,
            "pm10": float(self.pm10) if self.pm10 else None,
            "measured_at": self.measured_at.replace(tzinfo=timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
        }

class EnvironmentScore(db.Model):
    __tablename__ = 'environmental_scores'
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    sensor_id = db.Column(db.BigInteger, db.ForeignKey('sensor_data.id'), nullable=False)
    environmental_score = db.Column(db.Numeric(5, 2), nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=datetime.utcnow)
    sensor_data = db.relationship('SensorData', backref=db.backref('scores', lazy=True))

class AirKoreaData(db.Model):
    __tablename__ = 'air_korea_data'
    timestamp = db.Column(db.DateTime, primary_key=True)
    pm10_ug_m3_ = db.Column(db.Numeric(8, 3))
    pm2_5_ug_m3_ = db.Column(db.Numeric(8, 3))
    pm10_category = db.Column(db.Integer)
    pm2_5_category = db.Column(db.Integer)
    o3_ppm_ = db.Column(db.Numeric(5, 2))
    no2_ppm_ = db.Column(db.Numeric(5, 2))
    co_ppm_ = db.Column(db.Numeric(5, 2))
    so2_ppm_ = db.Column(db.Numeric(5, 2))

# ===================== 점수 계산 =====================
class AirQualityEvaluator:
    def __init__(self, pm25, pm10):
        self.pm25 = pm25
        self.pm10 = pm10

    def evaluate(self):
        def category(val, thresholds):
            if val <= thresholds[0]: return 1
            if val <= thresholds[1]: return 2
            if val <= thresholds[2]: return 3
            return 4
        c25 = category(self.pm25, [15, 35, 75])
        c10 = category(self.pm10, [30, 80, 150])
        return max(c25, c10)  # 1~4 반환

def calculate_environmental_score(pm2_5, pm10):
    return AirQualityEvaluator(float(pm2_5), float(pm10)).evaluate()

def process_environment_score(sensor_data):
    score = calculate_environmental_score(sensor_data.pm2_5 or 0, sensor_data.pm10 or 0)
    db.session.add(EnvironmentScore(sensor_id=sensor_data.id, environmental_score=score))
    db.session.commit()
    return score

# ===================== 유틸 =====================
def _to_float(s):
    if s is None: return None
    s = str(s).strip()
    if s in ("", "-", "nan", "NaN", "null", "None"): return None
    try: return float(s)
    except: return None

def _to_int(s):
    v = _to_float(s)
    return int(v) if v is not None else None

# ===================== 동국 API 전송 함수 (수정) =====================
def _score_to_speed(score: float) -> int:
    """
    환경 점수(1~4)를 동국 API 스펙(0~3)으로 변환.
    1->0(낮음) / 2->1 / 3->2 / 4->3(높음)
    """
    if score is None:
        return None
    try:
        return max(0, min(3, int(round(float(score) - 1))))
    except Exception:
        return None

def send_speed_to_donguk_api(score):
    """
    ✅ 헤더: donguk_key
    ✅ Body: {"speed": 0~3}
    """
    speed = _score_to_speed(score)
    if speed is None:
        print("[동국 API] 점수가 없어 전송하지 않습니다.")
        return

    headers = {
        "donguk_key": DONGUK_KEY
    }
    payload = {"speed": speed}

    try:
        print(f"[동국 API 전송 시도] {payload}")
        resp = requests.post(DONGUK_SPEED_URL, json=payload, headers=headers, timeout=5)
        print(f"[동국 API 응답] status={resp.status_code}, text={resp.text[:200]}")
    except requests.RequestException as e:
        print(f"[동국 API 오류] {e}")

# ===================== ESP32 업로드 엔드포인트 =====================
@app.route("/upload", methods=["POST"])
def upload_from_esp32():
    if not request.is_json:
        return jsonify({"success": False, "error": "Content-Type must be application/json"}), 415
    try:
        body = request.get_json()
        parts = [p.strip() for p in str(body.get("sensor_data", "")).split(",")]
        if len(parts) != 6:
            return jsonify({"success": False, "error": f"invalid payload (need 6 fields): {parts}"}), 400

        temperature = _to_float(parts[0])
        humidity    = _to_float(parts[1])
        co2eq       = _to_int(parts[2])
        tvoc        = _to_float(parts[3])
        pm2_5       = _to_float(parts[4])
        pm10        = _to_float(parts[5])

        rec = SensorData(
            temperature=temperature,
            humidity=humidity,
            co2eq=co2eq,
            tvoc=tvoc,
            pm2_5=pm2_5,
            pm10=pm10,
            measured_at=datetime.utcnow()
        )
        db.session.add(rec)
        db.session.commit()

        # 점수 계산 및 동국 API 전송 ✅
        score = float(process_environment_score(rec)) if rec.pm2_5 is not None and rec.pm10 is not None else None
        send_speed_to_donguk_api(score)  # ✅ 전송

        return jsonify({"success": True, "sensor_data": rec.to_dict(), "environmental_score": score}), 201

    except Exception as e:
        traceback.print_exc()
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# ===================== API =====================
@app.route("/api/sensor_data", methods=["GET", "POST"])
def sensor_data_endpoint():
    if request.method == "POST":
        data = request.get_json()
        rec = SensorData(
            temperature=data.get("temperature"),
            humidity=data.get("humidity"),
            co2eq=data.get("co2eq"),
            tvoc=data.get("tvoc"),
            pm1_0=data.get("pm1_0"),
            pm2_5=data.get("pm2_5"),
            pm10=data.get("pm10")
        )
        db.session.add(rec)
        db.session.commit()

        score = process_environment_score(rec)
        send_speed_to_donguk_api(float(score))  # ✅ 동국 API 전송 추가

        return jsonify({"success": True, "sensor_data": rec.to_dict(), "environmental_score": float(score)}), 201

    all_data = SensorData.query.order_by(SensorData.measured_at.desc()).all()
    return jsonify({"success": True, "sensor_data": [d.to_dict() for d in all_data]}), 200

@app.route("/api/scores", methods=["GET"])
def get_scores():
    scores = EnvironmentScore.query.order_by(EnvironmentScore.created_at.desc()).all()
    return jsonify({
        "success": True,
        "scores": [{
            "id": s.id,
            "score": float(s.environmental_score),
            "calculated_at": s.created_at.replace(tzinfo=timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S"),
            "sensor_data": s.sensor_data.to_dict() if s.sensor_data else None
        } for s in scores]
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/dashboard")
def show_dashboard():
    recent_data = SensorData.query.order_by(SensorData.measured_at.desc()).limit(20).all()
    sensor_data = []
    for s in recent_data:
        score = s.scores[0].environmental_score if s.scores else None
        sensor_data.append({
            "measured_at": s.measured_at.replace(tzinfo=timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M"),
            "temperature": float(s.temperature) if s.temperature else None,
            "humidity": float(s.humidity) if s.humidity else None,
            "co2eq": s.co2eq,
            "tvoc": float(s.tvoc) if s.tvoc else None,
            "pm2_5": float(s.pm2_5) if s.pm2_5 else None,
            "pm10": float(s.pm10) if s.pm10 else None,
            "environmental_score": float(score) if score else None
        })

    air_data = AirKoreaData.query.order_by(AirKoreaData.timestamp.desc()).limit(10).all()
    air_korea = []
    for a in air_data:
        air_korea.append({
            "timestamp": a.timestamp.replace(tzinfo=timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M"),
            "pm10": float(a.pm10_ug_m3_) if a.pm10_ug_m3_ else None,
            "pm2_5": float(a.pm2_5_ug_m3_) if a.pm2_5_ug_m3_ else None,
            "pm10_category": a.pm10_category,
            "pm2_5_category": a.pm2_5_category,
            "o3": float(a.o3_ppm_) if a.o3_ppm_ else None,
            "no2": float(a.no2_ppm_) if a.no2_ppm_ else None,
            "co": float(a.co_ppm_) if a.co_ppm_ else None,
            "so2": float(a.so2_ppm_) if a.so2_ppm_ else None
        })

    return render_template("dashboard.html", sensor_data=sensor_data, air_korea=air_korea)

# ===================== 실행 =====================
def background_sensor_task():
    while True:
        print("[백그라운드] (에어코리아 예시 생략)")
        time.sleep(3600)

if __name__ == '__main__':
    threading.Thread(target=background_sensor_task, daemon=True).start()
    app.run(debug=True, host='0.0.0.0', port=5000)
