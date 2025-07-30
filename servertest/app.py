import requests
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
import threading
import urllib.parse
import time

app = Flask(__name__)
CORS(app)

# ✅ DB 연결 설정
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:ckdudwns%40%401@127.0.0.1:3306/environmental_monitoring'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# ✅ DB 모델 정의
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
            "measured_at": self.measured_at.strftime("%Y-%m-%d %H:%M:%S")
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


# ✅ 점수 계산 클래스
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
            "보통": 2,
            "나쁨": 3,
            "매우 나쁨": 4
        }

    def get_pm25_category(self):
        if self.pm25_value <= 15:
            return "좋음"
        elif self.pm25_value <= 35:
            return "보통"
        elif self.pm25_value <= 75:
            return "나쁨"
        else:
            return "매우 나쁨"

    def get_pm10_category(self):
        if self.pm10_value <= 30:
            return "좋음"
        elif self.pm10_value <= 80:
            return "보통"
        elif self.pm10_value <= 150:
            return "나쁨"
        else:
            return "매우 나쁨"

    def evaluate(self):
        pm25_category = self.get_pm25_category()
        pm10_category = self.get_pm10_category()
        final_category = pm25_category if self.category_priority[pm25_category] >= self.category_priority[pm10_category] else pm10_category
        return self.final_score_map[final_category]


# ✅ 점수 계산 및 저장
def calculate_environmental_score(pm2_5, pm10):
    evaluator = AirQualityEvaluator(float(pm2_5), float(pm10))
    return evaluator.evaluate()


def process_environment_score(sensor_data):
    score = calculate_environmental_score(sensor_data.pm2_5 or 0, sensor_data.pm10 or 0)
    score_entry = EnvironmentScore(
        sensor_id=sensor_data.id,
        environmental_score=score
    )
    db.session.add(score_entry)
    db.session.commit()
    return score


# ✅ 에어코리아 API 호출 및 저장
def fetch_and_save_airkorea_data():
    SERVICE_KEY = "tlBcA73yJuLT1PSGixHpbHwLcINQEVtZ0g5xfd2E5/+qZUSmPK1hSFACjbw+pauS2glnKPhOPUcniVoBRkGfpA=="
    params = {
        'serviceKey': urllib.parse.unquote(SERVICE_KEY),
        'stationName': '삼천동',
        'dataTerm': 'DAILY',
        'pageNo': '1',
        'numOfRows': '1',
        'returnType': 'json',
        'ver': '1.3'
    }
    url = "http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"

    try:
        response = requests.get(url, params=params, verify=False)
        if response.status_code == 200:
            data = response.json()
            if data['response']['header']['resultCode'] == "00":
                item = data['response']['body']['items'][0]
                timestamp = datetime.strptime(item['dataTime'], "%Y-%m-%d %H:%M")

                if not AirKoreaData.query.filter_by(timestamp=timestamp).first():
                    record = AirKoreaData(
                        timestamp=timestamp,
                        pm10_ug_m3_=float(item['pm10Value']) if item['pm10Value'] != "-" else None,
                        pm2_5_ug_m3_=float(item['pm25Value']) if item['pm25Value'] != "-" else None,
                        pm10_category=int(item.get('pm10Grade')) if item.get('pm10Grade') and item.get('pm10Grade').isdigit() else None,
                        pm2_5_category=int(item.get('pm25Grade')) if item.get('pm25Grade') and item.get('pm25Grade').isdigit() else None,
                        o3_ppm_=float(item['o3Value']) if item['o3Value'] != "-" else None,
                        no2_ppm_=float(item['no2Value']) if item['no2Value'] != "-" else None,
                        co_ppm_=float(item['coValue']) if item['coValue'] != "-" else None,
                        so2_ppm_=float(item['so2Value']) if item['so2Value'] != "-" else None
                    )
                    db.session.add(record)
                    db.session.commit()
                    print("✅ 에어코리아 데이터 저장 완료")
                else:
                    print("ℹ️ 이미 저장된 데이터입니다.")
            else:
                print("❌ API 오류:", data['response']['header']['resultMsg'])
        else:
            print("❌ HTTP 오류:", response.status_code)
    except Exception as e:
        print("❌ 요청 실패:", str(e))


# ✅ 외부 API 전송 예시 (선택적 사용)
def send_environmental_score_to_external_api(score_data):
    external_api_url = "https://externalapi.com/receive_score"
    try:
        response = requests.post(external_api_url, json=score_data)
        if response.status_code == 200:
            print("✅ 외부 API 전송 성공")
        else:
            print("❌ 외부 API 전송 실패:", response.status_code, response.text)
    except Exception as e:
        print("❌ 외부 API 오류:", str(e))


# ✅ 센서 데이터 수신 API
@app.route("/api/sensor_data", methods=["GET", "POST"])
def sensor_data_endpoint():
    if request.method == "POST":
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "JSON 데이터를 받지 못함"}), 400

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
            "environmental_score": environmental_score,
            "measured_at": sensor_data.measured_at.strftime("%Y-%m-%d %H:%M:%S")
        })

        return jsonify({
            "success": True,
            "sensor_data": sensor_data.to_dict(),
            "environmental_score": float(environmental_score)
        }), 201

    else:
        all_data = SensorData.query.order_by(SensorData.measured_at.desc()).all()
        return jsonify({
            "success": True,
            "sensor_data": [d.to_dict() for d in all_data]
        }), 200


# ✅ 점수 데이터 조회 API
@app.route("/api/scores", methods=["GET"])
def get_scores():
    try:
        scores = EnvironmentScore.query.order_by(EnvironmentScore.created_at.desc()).all()
        result = [{
            "id": s.id,
            "score": float(s.environmental_score),
            "calculated_at": s.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "sensor_data": s.sensor_data.to_dict() if s.sensor_data else None
        } for s in scores]

        return jsonify({"success": True, "scores": result}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ✅ 에어코리아 데이터 수동 조회 API
@app.route("/api/airkorea", methods=["GET"])
def get_airkorea_data():
    try:
        data = AirKoreaData.query.order_by(AirKoreaData.timestamp.desc()).limit(10).all()
        result = [{
            "timestamp": d.timestamp.strftime("%Y-%m-%d %H:%M"),
            "pm10": float(d.pm10_ug_m3_) if d.pm10_ug_m3_ else None,
            "pm2_5": float(d.pm2_5_ug_m3_) if d.pm2_5_ug_m3_ else None,
            "pm10_category": d.pm10_category,
            "pm2_5_category": d.pm2_5_category
        } for d in data]

        return jsonify({"success": True, "data": result}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ✅ 백그라운드 태스크
def background_sensor_task():
    while True:
        print("[백그라운드] 에어코리아 데이터 수집 중...")
        with app.app_context():  # ✅ Flask 컨텍스트 활성화
            fetch_and_save_airkorea_data()
        time.sleep(3600)  # 1시간마다 실행


# ✅ 앱 실행
if __name__ == '__main__':
    threading.Thread(target=background_sensor_task, daemon=True).start()
    app.run(debug=True, host='127.0.0.1', port=5000)
