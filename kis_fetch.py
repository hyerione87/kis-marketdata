"""한국투자증권 Open API 시세 수집 (조회 전용, 주문·계좌 API는 쓰지 않음).

GitHub Actions에서 평일 1회 실행 (토큰은 하루 1회만 발급): KIS_APPKEY, KIS_APPSECRET 환경변수 필요.
결과
  data/kis_markets.json   행 {date, group, symbol, name, unit, close, chg, chg_pct}  (이전 파일에 이어 붙임, 최근 760일)
                          group: 지수 / 환율 / 금리 / 원자재. 금리는 close가 % 수익률, chg는 %p 차이
  data/kis_rates_now.json 금리 종합 API 스냅샷 (국내·해외 금리 현재가, 확인용)
  data/kis_status.json    실행 시각, 항목별 성공/실패, 사용한 시장 구분, 최신 값
코드 출처: data/master/frgn_code.tsv (kis_codes.py가 KIS 공개 코드 파일에서 만듦)
"""
import json, os, sys, time, datetime as dt, urllib.request, urllib.parse

BASE = "https://openapi.koreainvestment.com:9443"
KEY, SECRET = os.environ["KIS_APPKEY"], os.environ["KIS_APPSECRET"]
OUT = sys.argv[1] if len(sys.argv) > 1 else "data"
os.makedirs(OUT, exist_ok=True)
KST = dt.timezone(dt.timedelta(hours=9))
today = dt.datetime.now(KST).date()
start = today - dt.timedelta(days=150)   # 1회 호출 최대 약 100영업일
keep_from = (today - dt.timedelta(days=760)).isoformat()

# (symbol, 이름, group, 단위, KIS 코드, 시도할 시장 구분 순서)
# 시장 구분: N 해외지수, X 환율, I 국채·금리, S 금·원자재 (KIS 문서 기준, 맞지 않으면 다음 구분을 시도)
IDX, FX, RATE, CMD = ["N"], ["X"], ["I", "N"], ["S", "N", "I"]
OVERSEAS = [
    # 미국 지수
    ("SPX", "S&P 500", "지수", "", "SPX", IDX), ("COMP", "나스닥", "지수", "", "COMP", IDX),
    ("DJI", "다우", "지수", "", ".DJI", IDX), ("NDX", "나스닥100", "지수", "", "NDX", IDX),
    ("SOX", "필라델피아 반도체", "지수", "", "SOX", IDX), ("VIX", "VIX", "지수", "", "VIX", IDX),
    # 아시아
    ("N225", "닛케이225", "지수", "", "JP#NI225", IDX), ("SSEC", "상해종합", "지수", "", "SHANG", IDX),
    ("CSI300", "CSI 300", "지수", "", "CH#000300", IDX), ("HSI", "항셍", "지수", "", "HK#HS", IDX),
    ("HSCE", "홍콩H", "지수", "", "HSCE", IDX), ("TWII", "대만 가권", "지수", "", "TW#WT", IDX),
    ("SENSEX", "인도 센섹스", "지수", "", "IN#BOMBAY", IDX), ("VNI", "베트남 VN", "지수", "", "VN#VNI", IDX),
    # 유럽
    ("SX5E", "유로스톡스50", "지수", "", "SX5E", IDX), ("DAX", "독일 DAX", "지수", "", "GR#DAX", IDX),
    ("FTSE", "영국 FTSE100", "지수", "", "GB#FTSE", IDX), ("CAC", "프랑스 CAC40", "지수", "", "FR#CAC", IDX),
    # 환율
    ("USDKRW", "원/달러", "환율", "원", "FX@KRW", FX), ("JPYKRW", "원/엔(100엔)", "환율", "원", "FX@KRWJS", FX),
    ("USDJPY", "엔/달러", "환율", "엔", "FX@JPY", FX), ("EURUSD", "달러/유로", "환율", "$", "FX@EUR", FX),
    ("USDCNY", "위안/달러", "환율", "위안", "FX@CNY", FX),
    # 해외 금리
    ("US1Y", "미국채 1년", "금리", "%", "Y0203", RATE), ("US10Y", "미국채 10년", "금리", "%", "Y0202", RATE),
    ("US30Y", "미국채 30년", "금리", "%", "Y0201", RATE), ("FFR", "미 연방기금금리", "금리", "%", "Y0204", RATE),
    ("JP10Y", "일본 국채 10년", "금리", "%", "Y0207", RATE),
    # 국내 금리
    ("KRCALL", "콜금리(1일)", "금리", "%", "Y0114", RATE), ("KRCD", "CD 91일", "금리", "%", "Y0112", RATE),
    ("KRCP", "CP 91일", "금리", "%", "Y0113", RATE), ("KR1Y", "국고채 1년", "금리", "%", "Y0104", RATE),
    ("KR3Y", "국고채 3년", "금리", "%", "Y0101", RATE), ("KR5Y", "국고채 5년", "금리", "%", "Y0105", RATE),
    ("KR10Y", "국고채 10년", "금리", "%", "Y0106", RATE), ("KR20Y", "국고채 20년", "금리", "%", "Y0116", RATE),
    ("KR30Y", "국고채 30년", "금리", "%", "Y0117", RATE), ("KRCORP", "회사채 3년 AA-", "금리", "%", "Y0102", RATE),
    ("KRCORPB", "회사채 3년 BBB-", "금리", "%", "Y0103", RATE),
    # 원자재
    ("GOLD", "금 현물(런던)", "원자재", "$", "GOLDLNPM", CMD), ("GOLDF", "금 선물(COMEX)", "원자재", "$", "NYGOLD", CMD),
    ("SILVER", "은 선물(COMEX)", "원자재", "$", "NYSILV", CMD), ("WTI", "WTI 근월", "원자재", "$", "WTIF", CMD),
    ("BRENT", "브렌트 근월", "원자재", "$", "BRENTF", CMD), ("DUBAI", "두바이유 현물", "원자재", "$", "DUBAIF", CMD),
    ("COPPER", "구리 현물(LME)", "원자재", "$", "LMECOC", CMD),
]
DOMESTIC = [("KOSPI", "코스피", "0001"), ("KOSDAQ", "코스닥", "1001"), ("KOSPI200", "코스피200", "2001")]
CLOSE_KEYS = ("ovrs_nmix_prpr", "bstp_nmix_prpr", "stck_clpr", "ovrs_prpr", "clpr", "prpr")


def http(method, path, headers=None, body=None, params=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"content-type": "application/json; charset=utf-8", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


tok = http("POST", "/oauth2/tokenP", body={"grant_type": "client_credentials", "appkey": KEY, "appsecret": SECRET})
if "access_token" not in tok:
    raise SystemExit(f"토큰 발급 실패: {tok}")
TOKEN = tok["access_token"]


def quote(path, tr_id, params):
    time.sleep(0.25)  # 초당 호출 제한 여유
    h = {"authorization": f"Bearer {TOKEN}", "appkey": KEY, "appsecret": SECRET, "tr_id": tr_id, "custtype": "P"}
    return http("GET", path, headers=h, params=params)


def parse(items):
    out = []
    for it in items or []:
        d = it.get("stck_bsop_date")
        c = next((it[k] for k in CLOSE_KEYS if it.get(k) not in (None, "")), None)
        try:
            v = float(c)
        except (TypeError, ValueError):
            continue
        if d and v != 0:
            out.append((f"{d[:4]}-{d[4:6]}-{d[6:]}", v))
    return out


new_rows, status = [], {}
d1, d2 = start.strftime("%Y%m%d"), today.strftime("%Y%m%d")


def keep(sym, name, group, unit, pts):
    for d, v in pts:
        new_rows.append({"date": d, "group": group, "symbol": sym, "name": name, "unit": unit, "close": v})


for sym, name, group, unit, code, mkts in OVERSEAS:
    tried = []
    for m in mkts:
        try:
            j = quote("/uapi/overseas-price/v1/quotations/inquire-daily-chartprice", "FHKST03030100",
                      {"FID_COND_MRKT_DIV_CODE": m, "FID_INPUT_ISCD": code, "FID_INPUT_DATE_1": d1,
                       "FID_INPUT_DATE_2": d2, "FID_PERIOD_DIV_CODE": "D"})
            pts = parse(j.get("output2"))
            tried.append(f"{m}:{len(pts)}:{j.get('msg1', '').strip()[:40]}")
            if pts:
                keep(sym, name, group, unit, pts)
                status[sym] = {"ok": True, "code": code, "mkt": m, "rows": len(pts)}
                break
        except Exception as e:
            tried.append(f"{m}:오류:{str(e)[:60]}")
    if sym not in status:
        status[sym] = {"ok": False, "code": code, "tried": tried}

for sym, name, code in DOMESTIC:
    try:
        j = quote("/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice", "FHKUP03500100",
                  {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code, "FID_INPUT_DATE_1": d1,
                   "FID_INPUT_DATE_2": d2, "FID_PERIOD_DIV_CODE": "D"})
        pts = parse(j.get("output2"))
        keep(sym, name, "지수", "", pts)
        status[sym] = {"ok": bool(pts), "code": code, "rows": len(pts), "msg": j.get("msg1", "").strip()}
    except Exception as e:
        status[sym] = {"ok": False, "code": code, "msg": str(e)[:200]}

# 금리 종합 스냅샷 (국내·해외 금리 현재가). 구분코드별로 받아 둔다
snap = {}
for cls in ("0", "1", "2"):
    try:
        j = quote("/uapi/domestic-stock/v1/quotations/comp-interest", "FHPST07020000",
                  {"FID_COND_MRKT_DIV_CODE": "I", "FID_COND_SCR_DIV_CODE": "20702",
                   "FID_DIV_CLS_CODE": cls, "FID_DIV_CLS_CODE1": ""})
        snap[cls] = {"msg": j.get("msg1", "").strip(), "output1": j.get("output1"), "output2": j.get("output2")}
    except Exception as e:
        snap[cls] = {"msg": str(e)[:200]}
json.dump({"run_at_kst": dt.datetime.now(KST).isoformat(timespec="seconds"), "by_div_cls": snap},
          open(os.path.join(OUT, "kis_rates_now.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# 이전 파일에 이어 붙이고 전일 대비 계산
path = os.path.join(OUT, "kis_markets.json")
meta = {s[0]: s for s in OVERSEAS}
merged = {}
if os.path.exists(path):
    for r in json.load(open(path, encoding="utf-8")):
        if "group" not in r:  # 1차 형식(지수만) 행 보정
            m = meta.get(r["symbol"])
            r["group"], r["unit"] = (m[2], m[3]) if m else ("지수", "")
        merged[(r["symbol"], r["date"])] = r
for r in new_rows:
    merged[(r["symbol"], r["date"])] = r
rows = sorted((r for r in merged.values() if r["date"] >= keep_from), key=lambda r: (r["symbol"], r["date"]))
prev = {}
for r in rows:
    p = prev.get(r["symbol"])
    r["chg"] = round(r["close"] - p, 4) if p is not None else None
    r["chg_pct"] = round((r["close"] / p - 1) * 100, 2) if p else None
    prev[r["symbol"]] = r["close"]
json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False)

latest = {}
for r in rows:
    latest[r["symbol"]] = r
for k, s in status.items():
    if k in latest:
        L = latest[k]
        s["latest"] = {"date": L["date"], "close": L["close"], "chg": L["chg"], "chg_pct": L["chg_pct"]}
json.dump({"run_at_kst": dt.datetime.now(KST).isoformat(timespec="seconds"), "status": status},
          open(os.path.join(OUT, "kis_status.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for k, s in status.items():
    print(k, "OK" if s["ok"] else "실패", s.get("mkt", ""), s.get("latest", s.get("tried", s.get("msg"))))
if not any(s["ok"] for s in status.values()):
    raise SystemExit("모든 항목 실패")
