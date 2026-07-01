#!/usr/bin/env python3
# update_data.py — GitHub Actions 크론이 실행. 표준 라이브러리만 사용(설치 불필요).
# 원/달러(open.er-api) + 미 국채 10Y/2Y(미국 재무부 공식 피드, 실패 시 Stooq 폴백)를 받아 data.json 기록.
# 어떤 값을 못 받으면 직전 data.json 값을 그대로 유지하므로 화면이 비지 않는다.

import json, urllib.request, datetime
import xml.etree.ElementTree as ET

TIMEOUT = 25
DATA = "data.json"
UA = {"User-Agent": "krw-monitor/1.1 (+github actions)"}


def load_prev():
    try:
        with open(DATA, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_bytes(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def get_json(url):
    return json.loads(get_bytes(url).decode("utf-8"))


def get_text(url):
    return get_bytes(url).decode("utf-8", "replace")


# ---------- 원/달러 (open.er-api, 키 불필요) ----------
def fetch_usdkrw():
    j = get_json("https://open.er-api.com/v6/latest/USD")
    v = float(j["rates"]["KRW"])
    if 500 < v < 3000:
        return round(v, 2)
    raise ValueError("KRW out of range: %s" % v)


# ---------- 미 국채: 미국 재무부 공식 '일별 국채 수익률 곡선' XML (키 불필요, 매 영업일 갱신) ----------
def _localname(tag):
    return tag.rsplit("}", 1)[-1]


def _parse_treasury_month(xml_text):
    root = ET.fromstring(xml_text)
    best = None  # (date, ten, two) — 그 달에서 가장 최근 영업일
    for props in root.iter():
        if _localname(props.tag) != "properties":
            continue
        v = {}
        for c in props:
            v[_localname(c.tag)] = (c.text or "").strip()
        d, ten, two = v.get("NEW_DATE", ""), v.get("BC_10YEAR", ""), v.get("BC_2YEAR", "")
        if d and ten and two and (best is None or d > best[0]):
            best = (d, ten, two)
    return best


def fetch_treasury_yields():
    now = datetime.datetime.now(datetime.timezone.utc)
    first = now.replace(day=1)
    prev = first - datetime.timedelta(days=1)  # 지난달 (월초/휴장 대비)
    best = None
    for ym in (now.strftime("%Y%m"), prev.strftime("%Y%m")):
        url = ("https://home.treasury.gov/resource-center/data-chart-center/"
               "interest-rates/pages/xml?data=daily_treasury_yield_curve"
               "&field_tdr_date_value_month=%s" % ym)
        try:
            rec = _parse_treasury_month(get_text(url))
        except Exception as e:
            print("treasury %s failed: %s" % (ym, e))
            rec = None
        if rec and (best is None or rec[0] > best[0]):
            best = rec
    if not best:
        raise ValueError("no treasury entries")
    ten, two = round(float(best[1]), 2), round(float(best[2]), 2)
    if not (0 < ten < 20 and 0 < two < 20):
        raise ValueError("yield out of range: %s / %s" % (ten, two))
    return ten, two, best[0][:10]


# ---------- 폴백: Stooq CSV ----------
def fetch_stooq_yield(symbol):
    csv = get_text("https://stooq.com/q/l/?s=%s&f=sd2t2c&h&e=csv" % symbol)
    rows = [ln for ln in csv.splitlines() if ln.strip()]
    v = float(rows[-1].split(",")[-1].strip())
    if 0 < v < 20:
        return round(v, 2)
    raise ValueError("stooq yield out of range: %s" % v)


def main():
    prev = load_prev()
    out = dict(prev)  # 실패 시 직전값 유지

    # 원/달러
    try:
        new_krw = fetch_usdkrw()
        out["usdkrw_prev"] = prev.get("usdkrw", new_krw)
        out["usdkrw"] = new_krw
    except Exception as e:
        print("usdkrw failed, keeping previous:", e)

    # 미 국채 10Y / 2Y — 재무부 공식 피드 우선, 실패 시 Stooq 폴백
    try:
        ten, two, tdate = fetch_treasury_yields()
        out["ust10y"], out["ust2y"], out["ust_date"] = ten, two, tdate
        print("treasury ok:", ten, two, tdate)
    except Exception as e:
        print("treasury failed, trying stooq:", e)
        for key, sym in (("ust10y", "10usy.b"), ("ust2y", "2usy.b")):
            try:
                out[key] = fetch_stooq_yield(sym)
                print("%s via stooq: %s" % (key, out[key]))
            except Exception as e2:
                print("%s stooq failed, keeping previous: %s" % (key, e2))

    out["updatedAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("wrote %s: %s" % (DATA, out))


if __name__ == "__main__":
    main()
