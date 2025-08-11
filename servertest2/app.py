# app.py
from flask import Flask, request, render_template, redirect, url_for, jsonify   # ← jsonify 추가
import re
import requests
import urllib.parse
from pyproj import Transformer
from datetime import datetime
from dateutil.relativedelta import relativedelta  # pip install python-dateutil

app = Flask(__name__)

# 🔑 API Keys
KAKAO_API_KEY = "7c5ffe1b2f9e318d2bfa882a539bb429"
AIRKOREA_SERVICE_KEY = "tlBcA73yJuLT1PSGixHpbHwLcINQEVtZ0g5xfd2E5/+qZUSmPK1hSFACjbw+pauS2glnKPhOPUcniVoBRkGfpA=="

# ---------------------------
# 유틸
# ---------------------------
def preprocess_address(address: str) -> str:
    address = address.strip()
    address = re.sub(r'\s+', ' ', address)
    address = re.sub(r'[(),."\'`]', '', address)
    address = re.sub(r'\s+\d{1,4}(?:층|호|동)\s*$', '', address)
    return address

def is_valid_road_address(address: str) -> bool:
    pattern = r"^[가-힣]+\s[가-힣]+\s[가-힣]+\s[가-힣0-9]+(?:로|길)\s?\d{1,3}(?:-\d{1,3})?$"
    return bool(re.match(pattern, address.strip()))

def convert_to_tm(lat: float, lon: float):
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    x, y = transformer.transform(lon, lat)
    return x, y

# ---------------------------
# (NEW) Arduino/ESP 업로드 엔드포인트
# ---------------------------
@app.route("/upload", methods=["POST"])
def upload_sensor_data():
    """
    ESP32/ESP8266에서 전송하는 JSON:
      {"sensor_data": "Temp,Humi,CO2eq,TVOC,PM2,PM3"}
    또는 7개 값인 경우:
      {"sensor_data": "Temp,Humi,CO2eq,TVOC,PM1,PM2,PM3"}
    """
    try:
        data = request.get_json(silent=True) or {}
        payload = (data.get("sensor_data") or "").strip()

        # 폼/바이너리로 올 경우 대비
        if not payload:
            if request.form.get("sensor_data"):
                payload = request.form.get("sensor_data").strip()
            elif request.data:
                payload = request.data.decode("utf-8").strip()

        if not payload:
            return jsonify({"status": "error", "message": "sensor_data required"}), 400

        parts = [p.strip() for p in payload.split(",") if p.strip() != ""]
        parsed = {}

        if len(parts) == 6:
            # Temp, Humi, CO2eq, TVOC, PM2, PM3
            parsed = {
                "Temp": parts[0],
                "Humi": parts[1],
                "CO2eq": parts[2],
                "TVOC": parts[3],
                "PM2": parts[4],
                "PM3": parts[5],
            }
        elif len(parts) >= 7:
            # Temp, Humi, CO2eq, TVOC, PM1, PM2, PM3 (추가 항목이 더 있어도 앞 7개만)
            parsed = {
                "Temp": parts[0],
                "Humi": parts[1],
                "CO2eq": parts[2],
                "TVOC": parts[3],
                "PM1": parts[4],
                "PM2": parts[5],
                "PM3": parts[6],
            }
        else:
            return jsonify({"status": "error", "message": f"invalid sensor_data format: {parts}"}), 400

        parsed["received_at"] = datetime.utcnow().isoformat() + "Z"

        # TODO: 여기서 DB 저장 또는 추가 처리 수행 가능
        # ex) save_to_db(parsed)

        return jsonify({"status": "ok", "data": parsed}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

# ---------------------------
# 라우트 (기존 그대로)
# ---------------------------
@app.route("/", methods=["GET"])
def index():
    """검색 폼 페이지"""
    q = request.args.get("q", "")  # 이전 검색어 유지용(옵션)
    error = request.args.get("error", "")
    return render_template("index.html", q=q, error=error)

@app.route("/search", methods=["POST"])
def search():
    """폼 제출 처리 → /air-quality로 리다이렉트(GET)"""
    q = (request.form.get("q") or "").strip()
    if not q:
        return redirect(url_for("index", error="주소/장소명을 입력하세요."))
    return redirect(url_for("air_quality_view", q=q))

@app.route("/air-quality", methods=["GET"])
def air_quality_view():
    # 쿼리 파라미터로 검색어 받기
    raw_query = (request.args.get("q") or request.args.get("address") or "").strip()
    if not raw_query:
        return redirect(url_for("index", error="주소/장소명을 입력하세요."))

    q = preprocess_address(raw_query)

    # 1) 카카오 검색 (도로명/키워드 자동 판별)
    try:
        if is_valid_road_address(q):
            search_type = "도로명 주소"
            url = "https://dapi.kakao.com/v2/local/search/address.json"
            params = {"query": q}
        else:
            search_type = "장소명(키워드)"
            url = "https://dapi.kakao.com/v2/local/search/keyword.json"
            params = {"query": q}

        headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
        resp = requests.get(url, headers=headers, params=params, timeout=6)
        resp.raise_for_status()
        docs = resp.json().get("documents", [])
        if not docs:
            return render_template(
                "index.html",
                q=raw_query,
                error=f"'{raw_query}'에 대한 검색 결과가 없습니다."
            ), 404

        first = docs[0]
        if search_type == "도로명 주소":
            display_address = first["address"]["address_name"]
            lat = float(first["y"]); lon = float(first["x"])
            place_name = None
        else:
            display_address = first.get("road_address_name") or first.get("address_name") or "-"
            lat = float(first.get("y")); lon = float(first.get("x"))
            place_name = first.get("place_name")

    except Exception as e:
        return render_template("index.html", q=raw_query, error=f"Kakao API 오류: {e}"), 502

    # 2) TM 좌표
    tmX, tmY = convert_to_tm(lat, lon)

    # 3) 가까운 측정소
    try:
        msr_url = "http://apis.data.go.kr/B552584/MsrstnInfoInqireSvc/getNearbyMsrstnList"
        msr_params = {
            "serviceKey": urllib.parse.unquote(AIRKOREA_SERVICE_KEY),
            "returnType": "json",
            "tmX": tmX,
            "tmY": tmY,
            "ver": "1.0"
        }
        msr_resp = requests.get(msr_url, params=msr_params, timeout=6)
        msr_resp.raise_for_status()
        items = msr_resp.json().get("response", {}).get("body", {}).get("items", [])
        if not items:
            return render_template("index.html", q=raw_query, error="가까운 측정소를 찾을 수 없습니다."), 404
        stations = [{"stationName": it["stationName"], "addr": it["addr"]} for it in items[:2]]
    except Exception as e:
        return render_template("index.html", q=raw_query, error=f"측정소 조회 API 오류: {e}"), 502

    # 4) 실시간
    realtime_url = "http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"
    realtime = []
    for s in stations:
        try:
            p = {
                "serviceKey": urllib.parse.unquote(AIRKOREA_SERVICE_KEY),
                "stationName": s["stationName"],
                "dataTerm": "Daily",
                "ver": "1.3",
                "pageNo": "1",
                "numOfRows": "1",
                "returnType": "json"
            }
            r = requests.get(realtime_url, params=p, timeout=6)
            r.raise_for_status()
            its = r.json().get("response", {}).get("body", {}).get("items", [])
            if its:
                it = its[0]
                realtime.append({
                    "stationName": s["stationName"],
                    "address": s["addr"],
                    "timestamp": it.get("dataTime"),
                    "pm10_ug_m3": it.get("pm10Value"),
                    "pm10_category": it.get("pm10Grade", "N/A"),
                    "pm2_5_ug_m3": it.get("pm25Value"),
                    "pm2_5_category": it.get("pm25Grade", "N/A")
                })
        except Exception:
            realtime.append({
                "stationName": s["stationName"],
                "address": s["addr"],
                "timestamp": "오류",
                "pm10_ug_m3": "-",
                "pm10_category": "-",
                "pm2_5_ug_m3": "-",
                "pm2_5_category": "-"
            })

    # 5) 월간 (지난달~이번달)
    today = datetime.today()
    inq_end = today.strftime("%Y%m")
    inq_begin = (today - relativedelta(months=1)).strftime("%Y%m")

    monthly_url = "http://apis.data.go.kr/B552584/ArpltnStatsSvc/getMsrstnAcctoRMmrg"
    monthly = []
    for s in stations:
        try:
            p = {
                "serviceKey": urllib.parse.unquote(AIRKOREA_SERVICE_KEY),
                "returnType": "json",
                "inqBginMm": inq_begin,
                "inqEndMm": inq_end,
                "msrstnName": s["stationName"]
            }
            res = requests.get(monthly_url, params=p, timeout=6)
            res.raise_for_status()
            its = res.json().get("response", {}).get("body", {}).get("items", [])
            for it in its:
                monthly.append({
                    "stationName": it.get("msrstnName"),
                    "month": it.get("msurMm"),
                    "pm10_avg": it.get("pm10Value"),
                    "pm2_5_avg": it.get("pm25Value")
                })
        except Exception:
            monthly.append({
                "stationName": s["stationName"],
                "month": f"{inq_begin}-{inq_end}",
                "pm10_avg": "-",
                "pm2_5_avg": "-"
            })

    return render_template(
        "result.html",
        raw_query=raw_query,
        search_type=search_type,
        place_name=place_name,
        address=display_address,
        lat=lat, lon=lon, tmX=round(tmX, 3), tmY=round(tmY, 3),
        realtime=realtime,
        monthly=monthly,
        month_range={"begin": inq_begin, "end": inq_end}
    )

if __name__ == "__main__":
    # 홈에서 직접 검색: http://127.0.0.1:5000/
    app.run(host="0.0.0.0", port=5000, debug=True)
