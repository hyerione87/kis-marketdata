"""한투 종목 코드 마스터 파일 정리 (API 호출·토큰 발급 없음).

KIS가 공개 배포하는 코드 파일을 받아 data/master/ 에 사람이 읽을 수 있게 저장한다.
  frgn_code.tsv   해외지수·환율·국채·금선물 등 (구분, 코드, 영문명, 한글명) — 개별 주식(Q·H)은 제외
  frgn_summary.txt 구분별 건수
  idxcode.tsv     국내 업종·지수 코드
"""
import io, os, sys, zipfile, urllib.request, collections

OUT = os.path.join(sys.argv[1] if len(sys.argv) > 1 else "data", "master")
os.makedirs(OUT, exist_ok=True)
URL = "https://new.real.download.dws.co.kr/common/master/"


def fetch(name):
    raw = urllib.request.urlopen(URL + name + ".zip", timeout=60).read()
    z = zipfile.ZipFile(io.BytesIO(raw))
    return z.read(z.namelist()[0]).decode("cp949", "replace")


rows, cnt = [], collections.Counter()
for line in fetch("frgn_code.mst").splitlines():
    g = line[:1]
    if g == "X":
        sym, en, ko = line[1:11].strip(), line[11:40].strip(), line[40:80].strip()
    else:
        sym, en, ko = line[1:11].strip(), line[11:50].strip(), line[50:75].strip()
    cnt[g] += 1
    if g not in ("Q", "H"):
        rows.append(f"{g}\t{sym}\t{en}\t{ko}")
open(os.path.join(OUT, "frgn_code.tsv"), "w", encoding="utf-8").write("구분\t코드\t영문명\t한글명\n" + "\n".join(rows) + "\n")
open(os.path.join(OUT, "frgn_summary.txt"), "w", encoding="utf-8").write(
    "\n".join(f"{g}\t{n}" for g, n in sorted(cnt.items())) + "\n")

try:
    idx = fetch("idxcode.mst")
    open(os.path.join(OUT, "idxcode.tsv"), "w", encoding="utf-8").write(idx)
except Exception as e:
    open(os.path.join(OUT, "idxcode.tsv"), "w", encoding="utf-8").write(f"실패: {e}\n")
print(dict(cnt))
