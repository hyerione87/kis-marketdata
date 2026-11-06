"""한국투자증권 Open API 시세 수집 (조회 전용, 주문·계좌 API는 쓰지 않음).

GitHub Actions에서 매일 실행: KIS_APPKEY, KIS_APPSECRET 환경변수 필요.
결과
  data/kis_markets.json  행 {date, symbol, name, close, chg_pct}  (이전 파일에 이어 붙임, 최근 760일)
  data/kis_status.json   실행 시각, 항목별 성공/실패, 최신 날짜
  data/kis_codes.txt     해외지수 마스터에서 찾은 후보 코드(코드 확인용)
"""
import io, json, os, sys, time, zipfile, datetime as dt, urllib.request, urllib.parse

BASE = "https://openapi.koreainvestment.com:9443"
KEY, SECRET = os.environ["KIS_APPKEY"], os.environ["KIS_APPSECRET"]
OUT = sys.argv[1] if len(sys.argv) > 1 else "data"
os.makedirs(OUT, exist_ok=True)
KST = dt.timezone(dt.timedelta(hours=9))
today = dt.datetime.now(KST).date()
start = today - dt.timedelta(days=150)   # 1회 호출 최대 약 100영업일
keep_from = (today - dt.timedelta(days=760)).isoformat()


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
    time.sleep(0.3)  # 초당 호출 제한 여유
    h = {"authorization": f"Bearer {TOKEN}", "appkey": KEY, "appsecret": SECRET, "tr_id": tr_id, "custtype": "P"}
    return http("GET", path, headers=h, params=params)


# 1) 해외지수 마스터에서 코드 찾기 (KIS 공식 배포 파일)
WANT = {  # symbol: (한글/영문 이름에 들어갈 단어들, 기본 코드)
    "SPX": (["S&P500", "S&P 500"], "SPX"),
    "COMP": (["나스닥종합", "NASDAQ COMPOSITE"], "COMP"),
    "DJI": (["다우산업", "DOW JONES INDUSTRIAL"], ".DJI"),
    "SSEC": (["상해종합", "SHANGHAI COMPOSITE"], None),
    "HSI": (["항셍", "HANG SENG"], None),
    "N225": (["니케이225", "니케이 225", "NIKKEI 225", "NIKKEI225"], None),
    "TWII": (["대만가권", "TAIEX", "TAIWAN WEIGHTED"], None),
    "SENSEX": (["센섹스", "SENSEX"], None),
    "SX5E": (["유로스톡스50", "EURO STOXX 50"], None),
    "DAX": (["DAX"], None),
    "FTSE": (["FTSE100", "FTSE 100"], None),
}
NAMES = {"SPX": "S&P 500", "COMP": "나스닥", "DJI": "다우", "SSEC": "상해종합", "HSI": "항셍", "N225": "닛케이225",
         "TWII": "대만 가권", "SENSEX": "인도 센섹스", "SX5E": "유로스톡스50", "DAX": "독일 DAX", "FTSE": "영국 FTSE100",
         "KOSPI": "코스피", "KOSDAQ": "코스닥"}
codes, cand_lines = {}, []
try:
    raw = urllib.request.urlopen("https://new.real.download.dws.co.kr/common/master/frgn_code.mst.zip", timeout=60).read()
    text = zipfile.ZipFile(io.BytesIO(raw)).read("frgn_code.mst").decode("cp949", "replace")
    rows = []
    for line in text.splitlines():
        if line[:1] == "X":
            rows.append((line[:1], line[1:11].strip(), line[11:40].strip(), line[40:80].strip()))
        else:
            rows.append((line[:1], line[1:11].strip(), line[11:50].strip(), line[50:75].strip()))
    for g, sym, en, ko in rows:
        blob = f"{en} {ko}".upper().replace(" ", "")
        for key, (words, _) in WANT.items():
            if any(w.upper().replace(" ", "") in blob for w in words):
                cand_lines.append(f"{key}\t{g}\t{sym}\t{en}\t{ko}")
                if g == "N" and key not in codes:
                    codes[key] = sym
        if any(w in ko for w in ("달러", "국채", "금선물", "원화")) or any(w in en.upper() for w in ("USD", "TREASURY", "GOLD")):
            cand_lines.append(f"(참고)\t{g}\t{sym}\t{en}\t{ko}")
except Exception as e:
    cand_lines.append(f"마스터 파일 실패: {e}")
open(os.path.join(OUT, "kis_codes.txt"), "w", encoding="utf-8").write("\n".join(cand_lines) + "\n")
# 첫 실행(2026-11-06) 마스터 파일로 확인한 코드. 미국은 구분 P, 그 외 해외지수는 구분 W
codes = {"SPX": "SPX", "COMP": "COMP", "DJI": ".DJI", "SSEC": "SHANG", "HSI": "HK#HS", "N225": "JP#NI225",
         "TWII": "TW#WT", "SENSEX": "IN#BOMBAY", "SX5E": "SX5E", "DAX": "GR#DAX", "FTSE": "GB#FTSE"}


# 2) 시세 조회
new_rows, status = [], {}
d1, d2 = start.strftime("%Y%m%d"), today.strftime("%Y%m%d")


def add(symbol, items, close_key):
    n = 0
    for it in items or []:
        d, c = it.get("stck_bsop_date"), it.get(close_key)
        if not d or c in (None, "", "0", "0.00"):
            continue
        new_rows.append({"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "symbol": symbol, "name": NAMES[symbol], "close": float(c)})
        n += 1
    return n


for key, code in codes.items():
    if not code:
        status[key] = {"ok": False, "msg": "마스터에서 코드 못 찾음"}
        continue
    try:
        j = quote("/uapi/overseas-price/v1/quotations/inquire-daily-chartprice", "FHKST03030100",
                  {"FID_COND_MRKT_DIV_CODE": "N", "FID_INPUT_ISCD": code, "FID_INPUT_DATE_1": d1,
                   "FID_INPUT_DATE_2": d2, "FID_PERIOD_DIV_CODE": "D"})
        n = add(key, j.get("output2"), "ovrs_nmix_prpr")
        status[key] = {"ok": n > 0, "code": code, "rows": n, "msg": j.get("msg1", "").strip()}
    except Exception as e:
        status[key] = {"ok": False, "code": code, "msg": str(e)[:200]}

for key, code in {"KOSPI": "0001", "KOSDAQ": "1001"}.items():
    try:
        j = quote("/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice", "FHKUP03500100",
                  {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code, "FID_INPUT_DATE_1": d1,
                   "FID_INPUT_DATE_2": d2, "FID_PERIOD_DIV_CODE": "D"})
        n = add(key, j.get("output2"), "bstp_nmix_prpr")
        status[key] = {"ok": n > 0, "code": code, "rows": n, "msg": j.get("msg1", "").strip()}
    except Exception as e:
        status[key] = {"ok": False, "code": code, "msg": str(e)[:200]}

# 3) 이전 파일에 이어 붙이고 전일 대비 계산
path = os.path.join(OUT, "kis_markets.json")
merged = {}
if os.path.exists(path):
    for r in json.load(open(path, encoding="utf-8")):
        merged[(r["symbol"], r["date"])] = r
for r in new_rows:
    merged[(r["symbol"], r["date"])] = r
rows = sorted((r for r in merged.values() if r["date"] >= keep_from), key=lambda r: (r["symbol"], r["date"]))
prev = {}
for r in rows:
    p = prev.get(r["symbol"])
    r["chg_pct"] = round((r["close"] / p - 1) * 100, 2) if p else None
    prev[r["symbol"]] = r["close"]
json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False)

latest = {}
for r in rows:
    latest[r["symbol"]] = r
for k, s in status.items():
    if k in latest:
        s["latest"] = {"date": latest[k]["date"], "close": latest[k]["close"], "chg_pct": latest[k]["chg_pct"]}
json.dump({"run_at_kst": dt.datetime.now(KST).isoformat(timespec="seconds"), "status": status},
          open(os.path.join(OUT, "kis_status.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for k, s in status.items():
    print(k, "OK" if s["ok"] else "실패", s.get("code"), s.get("latest", s.get("msg")))
if not any(s["ok"] for s in status.values()):
    raise SystemExit("모든 항목 실패")
