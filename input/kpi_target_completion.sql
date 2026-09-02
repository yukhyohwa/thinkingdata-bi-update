/*
================================================================================
Game: Test
Description: Test
Environment: Trino
Table: ta.v_event_22
URL:https://ss-web.5xgames.com/#/tga/ide/22_5031?fromPanel=22_830
================================================================================
*/

WITH
-- 1. 7月KPI预估目标数据
KpiTarget AS (
    SELECT * FROM (
        VALUES
            (DATE '2026-09-01', 6128.0, 6128.0),
            (DATE '2026-09-02', 5335.0, 11463.0),
            (DATE '2026-09-03', 25253.0, 36716.0),
            (DATE '2026-09-04', 18821.0, 55537.0),
            (DATE '2026-09-05', 34849.0, 90387.0),
            (DATE '2026-09-06', 15463.0, 105849.0),
            (DATE '2026-09-07', 7580.0, 113429.0),
            (DATE '2026-09-08', 7722.0, 121151.0),
            (DATE '2026-09-09', 6957.0, 128108.0),
            (DATE '2026-09-10', 30949.0, 159057.0),
            (DATE '2026-09-11', 20652.0, 179708.0),
            (DATE '2026-09-12', 28422.0, 208131.0),
            (DATE '2026-09-13', 15259.0, 223390.0),
            (DATE '2026-09-14', 9060.0, 232449.0),
            (DATE '2026-09-15', 7777.0, 240226.0),
            (DATE '2026-09-16', 7877.0, 248103.0),
            (DATE '2026-09-17', 23280.0, 271383.0),
            (DATE '2026-09-18', 13485.0, 284869.0),
            (DATE '2026-09-19', 7873.0, 292742.0),
            (DATE '2026-09-20', 7362.0, 300104.0),
            (DATE '2026-09-21', 7287.0, 307391.0),
            (DATE '2026-09-22', 6076.0, 313467.0),
            (DATE '2026-09-23', 6066.0, 319533.0),
            (DATE '2026-09-24', 76810.0, 396343.0),
            (DATE '2026-09-25', 27368.0, 423711.0),
            (DATE '2026-09-26', 30620.0, 454331.0),
            (DATE '2026-09-27', 14509.0, 468840.0),
            (DATE '2026-09-28', 12218.0, 481058.0),
            (DATE '2026-09-29', 9781.0, 490839.0),
            (DATE '2026-09-30', 9788.0, 500627.0)
    ) AS t(target_date, est_daily_sales, est_cum_sales)
),

-- 2. 黑名单/内部测试账号过滤 (假设对应 19 的分群表)
UserBlacklist AS (
    SELECT 
       DISTINCT "#varchar_id" AS "#account_id"
     FROM user_result_cluster_22
    WHERE cluster_name IN ('internal_users')
),

-- 3. 计算每日实际收入
ActualDailyMetrics AS (
    SELECT
        CAST(v."$part_date" AS DATE) AS "date",
        SUM(CASE 
            WHEN v."$part_event" = 'PURCHASE' 
             AND JSON_EXTRACT_SCALAR(CAST(v.payload AS JSON), '$.validationtype') <> 'SANDBOX_RECEIPT' 
            THEN CAST(JSON_EXTRACT_SCALAR(CAST(v.payload AS JSON), '$.curamt') AS DOUBLE) / s5.exchange * s_cny.exchange 
            ELSE 0.0 
        END) AS actual_daily_sales
    FROM ta.v_event_22 v
    LEFT JOIN ta_dim.ta_exchange s5 ON v."$part_date" = s5.ex_date AND JSON_EXTRACT_SCALAR(CAST(v.payload AS JSON), '$.cur') = s5.currency
    LEFT JOIN ta_dim.ta_exchange s_cny ON v."$part_date" = s_cny.ex_date AND s_cny.currency = 'CNY'
    -- LEFT JOIN UserBlacklist s6 ON v."#account_id" = s6."#account_id"
    WHERE -- s6."#account_id" IS NULL AND 
          v."$part_date" >= '2026-09-01' AND v."$part_date" <= '2026-09-30'
      AND v."$part_event" IN ('PURCHASE')
    GROUP BY 1
)

-- 4. 最终汇总报表，包含每日和累计数据
SELECT 
    CAST(t.target_date AS VARCHAR) AS "日期",
    t.est_daily_sales AS "預估每日sales",
    t.est_cum_sales AS "預估月度累積sales",
    COALESCE(a.actual_daily_sales, 0.0) AS "實際每日sales",
    SUM(COALESCE(a.actual_daily_sales, 0.0)) OVER (ORDER BY t.target_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS "實際累計sales"
FROM KpiTarget t
LEFT JOIN ActualDailyMetrics a ON t.target_date = a."date"
ORDER BY t.target_date
