import requests

base_url = "http://localhost:5000/api"
sensor_data_url = f"{base_url}/sensor_data"  # 센서 데이터를 전송할 엔드포인트

# 아두이노 센서 데이터 (예시)
sensor_data = {
    "temperature": 25.5,
    "humidity": 60.0,
    "co2eq": 400,
    "tvoc": 0.05,
    "pm1_0": 2.5,
    "pm2_5": 3.0,
    "pm10": 5.0
}

# 센서 데이터 전송 요청
print(f"[POST] 센서 데이터 전송 요청: {sensor_data}")
response = requests.post(sensor_data_url, json=sensor_data)

# 응답 상태 코드 확인
if response.status_code != 201:
    print("❌ 센서 데이터 전송 실패:", response.status_code)
    print("응답 본문:", response.text)
    exit()

sensor_response = response.json()
print("✅ 센서 데이터 전송 성공:")
print(f"  📌 저장된 센서 데이터: {sensor_response.get('sensor_data')}")
print(f"  📈 평가 점수 (environmental_score): {sensor_response.get('environmental_score')}")

# 모든 센서 데이터 조회
print(f"\n[GET] 모든 센서 데이터 조회 요청 → {sensor_data_url}")
response = requests.get(sensor_data_url)

# 응답 상태 코드와 본문 확인
if response.status_code == 200 and response.headers.get("Content-Type", "").startswith("application/json"):
    try:
        data = response.json()
        print("📊 센서 데이터 목록:")
        for d in data.get("sensor_data", []):
            print(f"  - {d}")
    except ValueError:
        print("❌ 응답 본문이 JSON 형식이 아닙니다:", response.text)
else:
    print("❌ 응답이 비어있거나 JSON 형식이 아닙니다.")
