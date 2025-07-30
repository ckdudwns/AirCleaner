USE environmental_monitoring;

CREATE TABLE sensor_data (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    temperature DECIMAL(5,2),
    humidity DECIMAL(5,2),
    co2eq INT,
    tvoc DECIMAL(10,3),
    pm1_0 DECIMAL(8,3),
    pm2_5 DECIMAL(8,3),
    pm10 DECIMAL(8,3),
    measured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_measured_at (measured_at)
);

-- 2. air_korea_data(에어코리아 데이터 테이블)
CREATE TABLE air_korea_data (
    timestamp DATETIME, 
    pm10_ug_m3_ DECIMAL(8,3),
    pm2_5_ug_m3_ DECIMAL(8,3),
    pm10_category INT,
    pm2_5_category INT,
    o3_ppm_ DECIMAL(5,2),
    no2_ppm_ DECIMAL(5,2),
    co_ppm_ DECIMAL(5,2),
    so2_ppm_ DECIMAL(5,2)
);
-- 점수 테이블
CREATE TABLE environmental_scores (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
	sensor_id BIGINT NOT NULL,  
    environmental_score DECIMAL(5,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_created_at (created_at)
);