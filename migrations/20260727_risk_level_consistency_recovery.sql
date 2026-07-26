-- Recovery for a partially applied 20260727_risk_level_consistency.sql.
-- Run only when risk_level_code/name exist but are still nullable and legacy
-- risk_level remains present.

UPDATE fin_customer_profile
SET risk_level_code = CASE CONVERT(UPPER(TRIM(risk_level)) USING utf8mb4) COLLATE utf8mb4_unicode_ci
  WHEN 'C1' THEN 'C1' WHEN 'C2' THEN 'C2' WHEN 'C3' THEN 'C3'
  WHEN 'C4' THEN 'C4' WHEN 'C5' THEN 'C5'
  WHEN '保守型' THEN 'C1' WHEN '稳健型' THEN 'C2' WHEN '平衡型' THEN 'C3'
  WHEN '积极型' THEN 'C4' WHEN '进取型' THEN 'C4' WHEN '激进型' THEN 'C5'
  ELSE NULL
END;

UPDATE fin_customer_profile
SET risk_level_name = CASE risk_level_code
  WHEN 'C1' THEN '保守型'
  WHEN 'C2' THEN '稳健型'
  WHEN 'C3' THEN '平衡型'
  WHEN 'C4' THEN '积极型'
  WHEN 'C5' THEN '激进型'
  ELSE NULL
END;

ALTER TABLE fin_customer_profile
  MODIFY COLUMN risk_level_code VARCHAR(2) NOT NULL COMMENT '客户风险等级编码 C1-C5',
  MODIFY COLUMN risk_level_name VARCHAR(8) NOT NULL COMMENT '客户风险等级标准名称',
  ADD CONSTRAINT chk_fin_customer_profile_risk_level_pair CHECK (
    (risk_level_code = 'C1' AND risk_level_name = '保守型') OR
    (risk_level_code = 'C2' AND risk_level_name = '稳健型') OR
    (risk_level_code = 'C3' AND risk_level_name = '平衡型') OR
    (risk_level_code = 'C4' AND risk_level_name = '积极型') OR
    (risk_level_code = 'C5' AND risk_level_name = '激进型')
  ),
  DROP COLUMN risk_level;

ALTER TABLE fin_risk_assessment
  ADD CONSTRAINT chk_fin_risk_assessment_risk_level_code CHECK (
    risk_level IN ('C1', 'C2', 'C3', 'C4', 'C5')
  );
