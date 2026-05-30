#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOP 報告產生器：一鍵生成台股標的多因子深度分析報告
用法：python3 sop_report_generator.py <股票代號> [--name <公司名稱>]
範例：python3 sop_report_generator.py 2408 --name 南亞科
"""

import urllib.request
import urllib.parse
import json
import datetime
import time
import sys
import os
import argparse

# FinMind API 設定（複用現有 Token）
FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoibWF4Y2hhbiIsImVtYWlsIjoibWF4Z2RvZG9AZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.KP09kiX8jehcMEwcWbljKlgLve42NWNqWqlA-koW97E"


def get_finmind_url(dataset, data_id, start_date):
    url = f"{FINMIND_BASE}?dataset={dataset}&data_id={data_id}&start_date={start_date}"
    if FINMIND_TOKEN:
        url += f"&token={FINMIND_TOKEN}"
    return url


def fetch_json(url):
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"  API 存取失敗: {e}", file=sys.stderr)
        return None


def calculate_ma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def calculate_rsi(closes, period=5):
    if len(closes) < period + 1:
        return 50.0
    u_sum = 0.0
    d_sum = 0.0
    for i in range(len(closes) - period, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            u_sum += diff
        elif diff < 0:
            d_sum += abs(diff)
    if (u_sum + d_sum) == 0:
        return 50.0
    return round(100.0 * u_sum / (u_sum + d_sum), 2)


def fmt_amt(amt):
    if abs(amt) >= 100000000.0:
        return f"{amt / 100000000.0:.2f} 億元"
    elif abs(amt) >= 10000.0:
        return f"{amt / 10000.0:.0f} 萬元"
    elif abs(amt) > 0:
        return f"{amt:.0f} 元"
    else:
        return "0 元"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 階段一：基本面財務拐點診斷
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_fundamentals(sid):
    print("  階段一：正在採集基本面財報數據...")
    result = {
        "monthly_revenues": [],
        "quarterly_eps": [],
        "quarterly_gross_margin": [],
        "latest_rev_yoy": None,
        "is_rev_high": False,
        "eps_turning_up": False,
        "gross_margin_qoq_up": False,
    }

    # 月營收（近 24 個月）
    start_rev = (datetime.date.today() - datetime.timedelta(days=750)).strftime("%Y-%m-%d")
    rev_data = fetch_json(get_finmind_url("TaiwanStockMonthRevenue", sid, start_rev))
    time.sleep(0.15)

    if rev_data and rev_data.get("status") == 200 and rev_data.get("data"):
        sorted_revs = sorted(rev_data["data"], key=lambda x: x.get("date", ""))
        for r in sorted_revs:
            result["monthly_revenues"].append({
                "date": r.get("date", ""),
                "revenue": r.get("revenue", 0),
                "revenue_yoy": r.get("revenue_month", 0),
            })
        if len(sorted_revs) >= 2:
            latest = sorted_revs[-1].get("revenue", 0)
            prev_year_same = None
            latest_date = sorted_revs[-1].get("date", "")
            for r in sorted_revs[:-1]:
                rd = r.get("date", "")
                if rd and latest_date and rd[5:7] == latest_date[5:7] and int(rd[:4]) == int(latest_date[:4]) - 1:
                    prev_year_same = r.get("revenue", 0)
            if prev_year_same and prev_year_same > 0:
                result["latest_rev_yoy"] = round((latest - prev_year_same) / prev_year_same * 100, 2)
            max_hist = max(r.get("revenue", 0) for r in sorted_revs)
            result["is_rev_high"] = latest >= max_hist

    # 季 EPS 與毛利率
    start_eps = (datetime.date.today() - datetime.timedelta(days=900)).strftime("%Y-%m-%d")
    eps_data = fetch_json(get_finmind_url("TaiwanStockFinancialStatements", sid, start_eps))
    time.sleep(0.15)

    if eps_data and eps_data.get("status") == 200 and eps_data.get("data"):
        sorted_fin = sorted(eps_data["data"], key=lambda x: x.get("date", ""))
        eps_vals = []
        gm_vals = []
        for item in sorted_fin:
            t = item.get("type", "")
            v = item.get("value", 0)
            d = item.get("date", "")
            if t == "EPS":
                eps_vals.append({"date": d, "value": v})
            elif t == "GrossProfit" or t == "GrossProfitMargin":
                gm_vals.append({"date": d, "value": v})

        result["quarterly_eps"] = eps_vals[-8:] if len(eps_vals) > 8 else eps_vals
        result["quarterly_gross_margin"] = gm_vals[-8:] if len(gm_vals) > 8 else gm_vals

        if len(eps_vals) >= 2:
            result["eps_turning_up"] = eps_vals[-1]["value"] > eps_vals[-2]["value"]
        if len(gm_vals) >= 2:
            result["gross_margin_qoq_up"] = gm_vals[-1]["value"] > gm_vals[-2]["value"]

    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 階段二：機構與大戶籌碼鎖定分析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_chip_data(sid, close_price):
    print("  階段二：正在採集籌碼面數據...")
    result = {
        "foreign_5d_shares": 0,
        "foreign_10d_shares": 0,
        "foreign_20d_shares": 0,
        "trust_5d_shares": 0,
        "trust_10d_shares": 0,
        "trust_20d_shares": 0,
        "foreign_5d_amount": "0 元",
        "trust_5d_amount": "0 元",
        "margin_balance": None,
        "short_ratio": None,
    }

    # 三大法人買賣超（近 30 日）
    start_inst = (datetime.date.today() - datetime.timedelta(days=40)).strftime("%Y-%m-%d")
    inst_data = fetch_json(get_finmind_url("TaiwanStockInstitutionalInvestorsBuySell", sid, start_inst))
    time.sleep(0.15)

    if inst_data and inst_data.get("status") == 200 and inst_data.get("data"):
        daily_foreign = {}
        daily_trust = {}
        for r in inst_data["data"]:
            date_str = r.get("date")
            r_name = r.get("name") or ""
            if date_str:
                net_shares = r.get("buy", 0.0) - r.get("sell", 0.0)
                if "Foreign_Investor" in r_name:
                    daily_foreign[date_str] = daily_foreign.get(date_str, 0.0) + net_shares
                elif "Investment_Trust" in r_name:
                    daily_trust[date_str] = daily_trust.get(date_str, 0.0) + net_shares

        f_dates = sorted(daily_foreign.keys())
        t_dates = sorted(daily_trust.keys())

        def sum_last_n(data_dict, dates, n):
            return sum(data_dict[d] for d in dates[-n:]) / 1000.0 if len(dates) >= n else sum(data_dict[d] for d in dates) / 1000.0

        result["foreign_5d_shares"] = round(sum_last_n(daily_foreign, f_dates, 5), 1)
        result["foreign_10d_shares"] = round(sum_last_n(daily_foreign, f_dates, 10), 1)
        result["foreign_20d_shares"] = round(sum_last_n(daily_foreign, f_dates, 20), 1)
        result["trust_5d_shares"] = round(sum_last_n(daily_trust, t_dates, 5), 1)
        result["trust_10d_shares"] = round(sum_last_n(daily_trust, t_dates, 10), 1)
        result["trust_20d_shares"] = round(sum_last_n(daily_trust, t_dates, 20), 1)
        result["foreign_5d_amount"] = fmt_amt(result["foreign_5d_shares"] * 1000 * close_price)
        result["trust_5d_amount"] = fmt_amt(result["trust_5d_shares"] * 1000 * close_price)

    # 融資融券
    start_margin = (datetime.date.today() - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
    margin_data = fetch_json(get_finmind_url("TaiwanStockMarginPurchaseShortSale", sid, start_margin))
    time.sleep(0.15)

    if margin_data and margin_data.get("status") == 200 and margin_data.get("data"):
        latest_margin = sorted(margin_data["data"], key=lambda x: x.get("date", ""))
        if latest_margin:
            m = latest_margin[-1]
            mb = m.get("MarginPurchaseTodayBalance", 0)
            ss = m.get("ShortSaleTodayBalance", 0)
            result["margin_balance"] = mb
            result["short_ratio"] = round(ss / mb * 100, 2) if mb > 0 else 0.0

    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 階段四：技術面斐波那契回撤與均線定位
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_technical(sid):
    print("  階段四：正在採集技術面數據與計算斐波那契點位...")
    result = {
        "close": 0, "ma5": None, "ma10": None, "ma20": None,
        "ma60": None, "ma120": None, "ma200": None,
        "ma_bull_status": "無法判斷",
        "rsi5": 50.0, "rsi14": 50.0,
        "fib_high": 0, "fib_low": 0,
        "fib_0236": 0, "fib_0382": 0, "fib_0500": 0, "fib_0618": 0,
    }

    start_price = (datetime.date.today() - datetime.timedelta(days=500)).strftime("%Y-%m-%d")
    price_data = fetch_json(get_finmind_url("TaiwanStockPrice", sid, start_price))
    time.sleep(0.15)

    if not price_data or price_data.get("status") != 200 or not price_data.get("data"):
        print("  警告：無法取得價格數據。", file=sys.stderr)
        return result

    prices = sorted(price_data["data"], key=lambda x: x.get("date", ""))
    closes = [p["close"] for p in prices if "close" in p]
    highs = [p.get("max") or p.get("high") or 0 for p in prices]
    lows = [p.get("min") or p.get("low") or 0 for p in prices]

    if len(closes) < 20:
        return result

    result["close"] = closes[-1]
    result["ma5"] = round(calculate_ma(closes, 5), 2) if calculate_ma(closes, 5) else None
    result["ma10"] = round(calculate_ma(closes, 10), 2) if calculate_ma(closes, 10) else None
    result["ma20"] = round(calculate_ma(closes, 20), 2) if calculate_ma(closes, 20) else None
    result["ma60"] = round(calculate_ma(closes, 60), 2) if calculate_ma(closes, 60) else None
    result["ma120"] = round(calculate_ma(closes, 120), 2) if calculate_ma(closes, 120) else None
    result["ma200"] = round(calculate_ma(closes, 200), 2) if calculate_ma(closes, 200) else None

    # 多頭排列判定
    c = result["close"]
    ma20 = result["ma20"]
    ma60 = result["ma60"]
    ma120 = result["ma120"]
    if ma20 and ma60 and ma120:
        if c > ma20 > ma60 > ma120:
            result["ma_bull_status"] = "完全多頭排列（強勢）"
        elif c > ma20 and c > ma60:
            result["ma_bull_status"] = "中期多頭（股價站上月線與季線）"
        elif c > ma20:
            result["ma_bull_status"] = "短期偏多（股價站上月線）"
        else:
            result["ma_bull_status"] = "均線糾結或空頭排列"
    elif ma20:
        if c > ma20:
            result["ma_bull_status"] = "短期偏多（股價站上月線）"
        else:
            result["ma_bull_status"] = "短期偏空（股價低於月線）"

    # RSI
    result["rsi5"] = calculate_rsi(closes, 5)
    result["rsi14"] = calculate_rsi(closes, 14)

    # 斐波那契回撤（近 250 日波段高低點）
    lookback = min(250, len(highs))
    fib_high = max(highs[-lookback:])
    fib_low = min(l for l in lows[-lookback:] if l > 0)
    delta = fib_high - fib_low

    result["fib_high"] = fib_high
    result["fib_low"] = fib_low
    result["fib_0236"] = round(fib_high - 0.236 * delta, 1)
    result["fib_0382"] = round(fib_high - 0.382 * delta, 1)
    result["fib_0500"] = round(fib_high - 0.500 * delta, 1)
    result["fib_0618"] = round(fib_high - 0.618 * delta, 1)

    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SOP 五維雷達圖分數計算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def calculate_sop_scores(fund, chip, tech):
    scores = {
        "fundamental": 50,
        "chip": 50,
        "competition": 50,  # 預設中等，需人工調整
        "technical": 50,
        "valuation": 50,    # 預設中等，需人工調整
    }

    # 基本面分數
    f_score = 40
    if fund["eps_turning_up"]:
        f_score += 20
    if fund["gross_margin_qoq_up"]:
        f_score += 20
    if fund["is_rev_high"]:
        f_score += 20
    scores["fundamental"] = min(f_score, 100)

    # 籌碼面分數
    c_score = 30
    if chip["foreign_5d_shares"] > 0:
        c_score += 25
    if chip["trust_5d_shares"] > 0:
        c_score += 20
    if chip["foreign_5d_shares"] > 0 and chip["trust_5d_shares"] > 0:
        c_score += 15  # 雙法人共振加分
    if chip["margin_balance"] is not None and chip["short_ratio"] is not None:
        if chip["short_ratio"] < 5:
            c_score += 10  # 健康信用交易
    scores["chip"] = min(c_score, 100)

    # 技術面分數
    t_score = 30
    bull = tech["ma_bull_status"]
    if "完全多頭" in bull:
        t_score += 40
    elif "中期多頭" in bull:
        t_score += 25
    elif "短期偏多" in bull:
        t_score += 15
    if tech["rsi5"] > 50:
        t_score += 15
    if tech["rsi14"] > 50:
        t_score += 15
    scores["technical"] = min(t_score, 100)

    return scores


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Markdown 報告產出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def generate_report(sid, name, fund, chip, tech, scores):
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    close = tech["close"]

    # 季 EPS 表格
    eps_rows = ""
    for e in fund["quarterly_eps"]:
        eps_rows += f"| {e['date']} | {e['value']} 元 |\n"

    # 月營收表格（最近 6 個月）
    rev_rows = ""
    recent_revs = fund["monthly_revenues"][-6:]
    for r in recent_revs:
        rev_b = r["revenue"] / 100000000.0
        rev_rows += f"| {r['date']} | {rev_b:.2f} 億元 |\n"

    # 斐波那契表格
    delta = tech["fib_high"] - tech["fib_low"]

    report = f"""# {name}（{sid}）深度多因子分析報告

> 本報告由 SOP 報告產生器自動生成，基準日：{today_str}，收盤價：{close} 元。

---

## 階段一：基本面財務拐點診斷

### A. 近 6 個月月營收趨勢

| 月份 | 月營收 |
| :--- | :--- |
{rev_rows}
* **月營收是否創歷史新高**：{'是' if fund['is_rev_high'] else '否'}
* **最新月營收年增率（YoY）**：{f"{fund['latest_rev_yoy']}%" if fund['latest_rev_yoy'] is not None else '數據不足'}

### B. 近 8 季 EPS 趨勢

| 季度 | EPS |
| :--- | :--- |
{eps_rows}
* **EPS 是否呈現向上拐點（最近一季優於前一季）**：{'是' if fund['eps_turning_up'] else '否'}
* **毛利率是否呈現 QoQ 季增**：{'是' if fund['gross_margin_qoq_up'] else '否'}

### C. 原物料成本與定價轉嫁能力（需手動填寫）

> 請於此處手動填入該標的之上游原物料報價變動、高毛利產品比重與合約定價模式等資訊。

---

## 階段二：機構與大戶籌碼鎖定分析

### A. 三大法人買賣超

| 統計區間 | 外資累計買超（張） | 投信累計買超（張） |
| :--- | :--- | :--- |
| 近 5 日 | {chip['foreign_5d_shares']:,.1f} 張（{chip['foreign_5d_amount']}） | {chip['trust_5d_shares']:,.1f} 張（{chip['trust_5d_amount']}） |
| 近 10 日 | {chip['foreign_10d_shares']:,.1f} 張 | {chip['trust_10d_shares']:,.1f} 張 |
| 近 20 日 | {chip['foreign_20d_shares']:,.1f} 張 | {chip['trust_20d_shares']:,.1f} 張 |

### B. 信用交易健康度

* **融資餘額**：{f"{chip['margin_balance']:,} 張" if chip['margin_balance'] is not None else '數據不足'}
* **券資比**：{f"{chip['short_ratio']}%" if chip['short_ratio'] is not None else '數據不足'}

### C. 千張大戶持股比例（需手動填寫）

> 請於此處手動填入集保分散表之千張大戶持股比例數據。

---

## 階段三：競爭格局與供應份額橫向對比（需手動填寫）

> 請於此處手動填入：
> 1. 核心產品市佔率與供應鏈定位（第一 / 第二供應商）
> 2. 主要競爭對手之技術與產能限制
> 3. 當年度與次年度資本支出預估金額
> 4. 新廠折舊壓力評估

---

## 階段四：技術面斐波那契回撤與均線定位

### A. 移動平均線（MA）狀態

| 均線 | 價位（元） | 股價相對位置 |
| :--- | :--- | :--- |
| MA5 | {tech['ma5'] if tech['ma5'] else 'N/A'} | {'股價在上' if tech['ma5'] and close > tech['ma5'] else '股價在下'} |
| MA10 | {tech['ma10'] if tech['ma10'] else 'N/A'} | {'股價在上' if tech['ma10'] and close > tech['ma10'] else '股價在下'} |
| MA20（月線） | {tech['ma20'] if tech['ma20'] else 'N/A'} | {'股價在上' if tech['ma20'] and close > tech['ma20'] else '股價在下'} |
| MA60（季線） | {tech['ma60'] if tech['ma60'] else 'N/A'} | {'股價在上' if tech['ma60'] and close > tech['ma60'] else '股價在下'} |
| MA120（半年線） | {tech['ma120'] if tech['ma120'] else 'N/A'} | {'股價在上' if tech['ma120'] and close > tech['ma120'] else '股價在下'} |
| MA200（年線） | {tech['ma200'] if tech['ma200'] else 'N/A'} | {'股價在上' if tech['ma200'] and close > tech['ma200'] else '股價在下'} |

* **均線多頭排列狀態**：{tech['ma_bull_status']}
* **RSI(5)**：{tech['rsi5']}
* **RSI(14)**：{tech['rsi14']}

### B. 斐波那契回撤支撐區間計算

* 波段起漲點（$Price_{{low}}$）：**{tech['fib_low']} 元**
* 波段最高點（$Price_{{high}}$）：**{tech['fib_high']} 元**
* 波段價差：**{delta:.1f} 元**

| 回撤比例 | 計算公式 | 具體點位（元） | 技術意義 |
| :--- | :--- | :--- | :--- |
| **0.236** | {tech['fib_high']} - (0.236 x {delta:.1f}) | **{tech['fib_0236']} 元** | 強勢拉回支撐點 |
| **0.382** | {tech['fib_high']} - (0.382 x {delta:.1f}) | **{tech['fib_0382']} 元** | 黃金分割強支撐 |
| **0.500** | {tech['fib_high']} - (0.500 x {delta:.1f}) | **{tech['fib_0500']} 元** | 多空強弱分水嶺 |
| **0.618** | {tech['fib_high']} - (0.618 x {delta:.1f}) | **{tech['fib_0618']} 元** | 極限防禦點 |

---

## 階段五：法人預估盈餘共識與本益比區間（需手動填寫）

> 請於此處手動填入：
> 1. FactSet 或主流財經終端對當年度與次一年度之 EPS 預估共識中位數
> 2. 外資與本土券商之目標價區間
> 3. 基於上述 EPS 共識計算之 Forward PE 倍數

---

## SOP 五維雷達圖評分

| 維度 | 分數（0-100） | 評估依據 |
| :--- | :--- | :--- |
| **基本面** | {scores['fundamental']} | EPS 拐點 + 毛利率 QoQ + 營收新高 |
| **籌碼面** | {scores['chip']} | 法人買超共振 + 信用交易健康度 |
| **競爭力** | {scores['competition']} | 需手動評估 |
| **技術面** | {scores['technical']} | 均線排列 + RSI 強弱 |
| **估值面** | {scores['valuation']} | 需手動評估 |

---

## 交易決策與風險控管建議

### 分批建倉點位規劃
* **第一道買進防線**：**{tech['fib_0236']} 元** 附近（0.236 強勢回撤支撐）
* **第二道防禦型建倉防線**：**{tech['fib_0382']} 元** 附近（0.382 黃金分割支撐，預期與季線重疊）

### 停損防線
* 若股價收盤跌破 **{tech['fib_0500']} 元**（0.500 多空分水嶺），中期多頭結構轉弱，應減碼。
* 若股價收盤跌破 **{tech['fib_0618']} 元**（0.618 極限防禦），應無條件執行完全停損。
"""
    return report


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 主程式
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    parser = argparse.ArgumentParser(description="SOP 報告產生器：一鍵生成台股標的多因子深度分析報告")
    parser.add_argument("stock_id", help="股票代號（例如：2408）")
    parser.add_argument("--name", default=None, help="公司名稱（例如：南亞科）")
    args = parser.parse_args()

    sid = args.stock_id
    name = args.name or sid

    print(f"SOP 報告產生器啟動，正在分析：{name}（{sid}）")
    print("=" * 50)

    # 階段四先行：取得收盤價供後續計算
    tech = fetch_technical(sid)
    if tech["close"] == 0:
        print("錯誤：無法取得股價數據，終止。", file=sys.stderr)
        sys.exit(1)

    fund = fetch_fundamentals(sid)
    chip = fetch_chip_data(sid, tech["close"])
    scores = calculate_sop_scores(fund, chip, tech)

    print("  正在生成 Markdown 報告...")
    report = generate_report(sid, name, fund, chip, tech, scores)

    # 建立輸出目錄
    script_dir = os.path.dirname(os.path.abspath(__file__))
    reports_dir = os.path.join(os.path.dirname(script_dir), "reports")
    os.makedirs(reports_dir, exist_ok=True)

    output_path = os.path.join(reports_dir, f"{sid}_sop_report.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print("=" * 50)
    print(f"報告已成功輸出至: {output_path}")
    print(f"SOP 五維雷達圖評分: 基本面={scores['fundamental']} | 籌碼面={scores['chip']} | 競爭力={scores['competition']} | 技術面={scores['technical']} | 估值面={scores['valuation']}")


if __name__ == "__main__":
    main()
