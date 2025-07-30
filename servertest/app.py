import requests
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
import threading

app = Flask(__name__)
CORS(app)

# DB 연결 설정
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:ckdudwns%40%401@127.0.0.1:3306/environmental_monitoring'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ============================
# ✅ 미세먼지 기반 점수 계산 클래스
# ============================
class AirQualityEvaluator:
    def __init__(self, pm25_value, pm10_value):
        self.pm25_value = pm25_value
        self.pm10_value = pm10_value
        self.category_priority = {
            "좋음": 1,
            "보통": 2,
            "나쁨": 3,
            "매우 나쁨": 4
        }
        self.final_score_map = {
            "좋음": 1,
            "보통": 1.5,
            "나쁨": 2,
            "매우 나쁨": 2
        }

    def get_pm25_category(self):
        if self.pm25_value <= 15:
            return "좋음"
        elif 16 <= self.pm25_value <= 35:
            return "보통"
        elif 36 <= self.pm25_value <= 75:
            return "나쁨"
        else:
            return "매우 나쁨"

    def get_pm10_category(self):
        if self.pm10_value <= 30:
            return "좋음"
        elif 31 <= self.pm10_value <= 80:
            return "보통"
        elif 81 <= self.pm10_value <= 150:
            return "나쁨"
        else:
            return "매우 나쁨"

    def evaluate(self):
        pm25_category = self.get_pm25_category()
        pm10_category = self.get_pm10_category()

        if self.category_priority[pm25_category] >= self.category_priority[pm10_category]:
            final_category = pm25_category
        else:
            final_category = pm10_category

        return self.final_score_map[final_category]

# ============================
# ✅ DB 모델 정의
# ============================
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
            "temperature": self.temperature,
            "humidity": self.humidity,
            "co2eq": self.co2eq,
            "tvoc": self.tvoc,
            "pm1_0": self.pm1_0,
            "pm2_5": self.pm2_5,
            "pm10": self.pm10,
            "measured_at": self.measured_at.strftime("%Y-%m-%d %H:%M:%S")
        }

class EnvironmentScore(db.Model):
    __tablename__ = 'environment_scores'
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    sensor_data_id = db.Column(db.BigInteger, db.ForeignKey('sensor_data.id'), nullable=False)
    score = db.Column(db.Numeric(5, 2), nullable=False)
    calculated_at = db.Column(db.TIMESTAMP, default=datetime.utcnow)

    sensor_data = db.relationship('SensorData', backref=db.backref('environment_scores', uselist=False))

# ============================
# ✅ 환경 점수 계산 함수
# ============================
def calculate_environmental_score(pm2_5, pm10):
    evaluator = AirQualityEvaluator(float(pm2_5), float(pm10))
    return evaluator.evaluate()

def process_environment_score(sensor_data):
    score = calculate_environmental_score(sensor_data.pm2_5 or 0, sensor_data.pm10 or 0)

    score_entry = EnvironmentScore(
        sensor_data_id=sensor_data.id,
        score=score
    )
    db.session.add(score_entry)
    db.session.commit()
    return score

# ============================
# ✅ 외부 API 전송 함수
# ============================
def send_environmental_score_to_external_api(score_data):
    external_api_url = "https://externalapi.com/receive_score"  # 변경 필요
    try:
        response = requests.post(external_api_url, json=score_data)
        if response.status_code == 200:
            print("✅ 외부 API 전송 성공")
        else:
            print("❌ 외부 API 전송 실패:", response.status_code, response.text)
    except Exception as e:
        print("❌ 외부 API 오류:", str(e))

# ============================
# ✅ API 엔드포인트
# ============================
@app.route("/api/sensor_data", methods=["GET", "POST"])
def add_sensor_data():
    if request.method == "POST":
        if not request.is_json:
            return jsonify({"success": False, "error": "Content-Type must be application/json"}), 415

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Empty or invalid JSON payload"}), 400

        sensor_data = SensorData(
            temperature=data.get("temperature"),
            humidity=data.get("humidity"),
            co2eq=data.get("co2eq"),
            tvoc=data.get("tvoc"),
            pm1_0=data.get("pm1_0"),
            pm2_5=data.get("pm2_5"),
            pm10=data.get("pm10")
        )
        db.session.add(sensor_data)
        db.session.commit()

        environmental_score = process_environment_score(sensor_data)

        send_environmental_score_to_external_api({
            "environmental_scores": environmental_score,
            "measured_at": sensor_data.measured_at.strftime("%Y-%m-%d %H:%M:%S")
        })

        return jsonify({
            "success": True,
            "sensor_data": sensor_data.to_dict(),
            "environmental_scores": float(environmental_score)
        }), 201

    elif request.method == "GET":
        try:
            all_data = SensorData.query.order_by(SensorData.measured_at.desc()).all()
            return jsonify({
                "success": True,
                "sensor_data": [d.to_dict() for d in all_data]
            }), 200
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

@app.route('/', methods=['GET'])
def index():
    try:
        sensors = SensorData.query.all()
        return jsonify({
            'success': True,
            'sensor_data': [s.to_dict() for s in sensors]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/scores", methods=["GET"])
def get_scores():
    try:
        scores = EnvironmentScore.query.order_by(EnvironmentScore.calculated_at.desc()).all()
        result = []
        for s in scores:
            result.append({
                "id": s.id,
                "score": float(s.score),
                "calculated_at": s.calculated_at.strftime("%Y-%m-%d %H:%M:%S"),
                "sensor_data": s.sensor_data.to_dict() if s.sensor_data else None
            })

        return jsonify({
            "success": True,
            "scores": result
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================
# ✅ 백그라운드 태스크 예시
# ============================
def background_sensor_task():
    while True:
        print("[백그라운드] 센서 데이터를 주기적으로 처리 중...")
        import time
        time.sleep(60)

# ============================
# ✅ 앱 실행
# ============================
if __name__ == '__main__':
    threading.Thread(target=background_sensor_task, daemon=True).start()
    app.run(debug=True, host='127.0.0.1', port=5000)
