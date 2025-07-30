import requests
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
import threading

app = Flask(__name__)
CORS(app)

# MySQL DB 연결 설정
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:ckdudwns%40%401@127.0.0.1:3306/environmental_monitoring'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 환경 점수를 외부 API로 전송하는 함수
def send_environmental_score_to_external_api(score_data):
    external_api_url = "https://externalapi.com/receive_score"  # 실제 외부 API URL로 변경####################################################
    try:
        response = requests.post(external_api_url, json=score_data)
        if response.status_code == 200:
            print("성공적으로 외부 API에 전송되었습니다.")
        else:
            print("API 전송 실패:", response.status_code, response.text)
    except Exception as e:
        print("외부 API 전송 중 오류 발생:", str(e))

# SensorData 모델
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

# EnvironmentScore 모델
class EnvironmentScore(db.Model):
    __tablename__ = 'environment_score'
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    sensor_data_id = db.Column(db.BigInteger, db.ForeignKey('sensor_data.id'), nullable=False)
    score = db.Column(db.Numeric(5, 2), nullable=False)
    calculated_at = db.Column(db.TIMESTAMP, default=datetime.utcnow)

    sensor_data = db.relationship('SensorData', backref=db.backref('environment_score', uselist=False))

# 점수 계산 + DB 저장 함수
def process_environment_score(sensor_data):
    score = calculate_environmental_score(
        sensor_data.co2eq or 0,
        sensor_data.pm1_0 or 0,
        sensor_data.pm2_5 or 0,
        sensor_data.tvoc or 0
    )

    score_entry = EnvironmentScore(
        sensor_data_id=sensor_data.id,
        score=score
    )
    db.session.add(score_entry)
    db.session.commit()
    return score

# 점수 계산 함수
def calculate_environmental_score(co2eq, pm1_0, pm2_5, tvoc):
    score = 100 - (co2eq * 0.1 + pm1_0 * 0.5 + pm2_5 * 0.3 + tvoc * 0.2)
    return max(0, min(score, 100))

# API 엔드포인트
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

        # 점수 계산 및 저장 함수 호출
        environmental_score = process_environment_score(sensor_data)

        # 외부 API로 전송
        send_environmental_score_to_external_api({
            "environmental_score": environmental_score,
            "measured_at": sensor_data.measured_at.strftime("%Y-%m-%d %H:%M:%S")
        })

        return jsonify({
            "success": True,
            "sensor_data": sensor_data.to_dict(),
            "environmental_score": float(environmental_score)
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

# 메인 페이지 출력용
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

# 백그라운드 작업 예시
def background_sensor_task():
    while True:
        print("[백그라운드] 센서 데이터를 주기적으로 처리 중...")
        import time
        time.sleep(60)

# 실행
if __name__ == '__main__':
    threading.Thread(target=background_sensor_task, daemon=True).start()
    app.run(debug=True, host='127.0.0.1', port=5000)
