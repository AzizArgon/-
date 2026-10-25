"""Parser benchmark.

1) One file: AI requests, input size and time before/after the optimization of Phase 3.1:
  .venv/Scripts/python.exe scripts/benchmark_parser.py <price file>           # dry run, no AI calls
  .venv/Scripts/python.exe scripts/benchmark_parser.py <price file> --tokens  # + exact input tokens (free API)
  .venv/Scripts/python.exe scripts/benchmark_parser.py <price file> --live    # + real AI run, empty cache

2) Accuracy on the labelled set of tests/benchmark (Phase 7):
  .venv/Scripts/python.exe scripts/benchmark_parser.py suite --config rules
  .venv/Scripts/python.exe scripts/benchmark_parser.py suite --config gemini --live --tag before
  configs: rules (no AI), gemini, groq, gemini_nocheck (Gemini answers, AI specs not checked against the row).
  Every dataset runs with an empty in-memory cache (the working cache is not touched). AI answers are recorded per
  row in tests/benchmark/results/ai_<provider>.json; without --live only recorded answers are used (no requests),
  with --live the missing rows are asked live. Results: tests/benchmark/results/<config>_<tag>.json.
"""

import argparse
import asyncio
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.database import Base  # noqa: E402
from app.services import ai_parser, importer, text_import  # noqa: E402
from app.services.antifraud import check_offer  # noqa: E402
from app.services.catalog import completion_index, make_match_key, unique_completion  # noqa: E402
from app.services.importer import file_to_markdown, parse_clean_rows  # noqa: E402
from app.services.price_cleaner import cache_key, clean_markdown  # noqa: E402
from app.services.rule_parser import parse_by_rules  # noqa: E402
from app.services.spec_normalizer import SUSPECT, canonical_brand, normalize_specs  # noqa: E402

OLD_CHUNK_ROWS = 250  # Phase 3 version: every row, all cells, 250 rows per request
BENCH = Path(__file__).resolve().parents[1] / "tests" / "benchmark"
RESULTS = BENCH / "results"
GSHOP = Path(r"F:\claudy\samples\old_store_2023.xlsx")
RATE = 11_850  # the fixed UZS rate of the synthetic set
PROVIDERS = {"rules": None, "gemini": "gemini", "groq": "groq", "gemini_nocheck": "gemini"}
FIELDS = ("category", "brand", "model", "price", "currency", "condition")


def count_tokens(texts: list[str]) -> int:
    client = ai_parser._get_client()
    return sum(client.models.count_tokens(model=settings.gemini_model, contents=t).total_tokens for t in texts)


def file_report(args) -> None:
    path = Path(args.file)
    rows = clean_markdown(file_to_markdown(path.read_bytes(), path.name))

    # Before: whole rows ("r12 | name | article | price") were sent, 250 per request
    old_lines = [f"r{r.row} | " + " | ".join(r.cells) for r in rows]
    old_chunks = ["\n".join(old_lines[i : i + OLD_CHUNK_ROWS]) for i in range(0, len(old_lines), OLD_CHUNK_ROWS)]

    # After: rules first, only names of the remaining rows, big chunks
    pending = [r for r in rows if not parse_by_rules(r.name)]
    size = settings.parser_chunk_rows
    new_chunks = [ai_parser.format_chunk(pending[i : i + size]) for i in range(0, len(pending), size)]

    report = {
        "rows": len(rows),
        "before": {"ai_rows": len(rows), "requests": math.ceil(len(rows) / OLD_CHUNK_ROWS),
                   "input_chars": sum(map(len, old_chunks))},
        "after": {"rule_rows": len(rows) - len(pending), "ai_rows": len(pending), "requests": len(new_chunks),
                  "input_chars": sum(map(len, new_chunks))},
    }
    if args.tokens:
        report["before"]["input_tokens"] = count_tokens(old_chunks)
        report["after"]["input_tokens"] = count_tokens(new_chunks)
    if args.live:
        stats: dict = {}
        with _empty_db() as db:
            parsed = asyncio.run(parse_clean_rows(db, rows, stats))
        report["after_live"] = stats | {"parsed_rows": len(parsed)}
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _empty_db():
    """Empty in-memory cache: measures a cold run, the real cache is not touched."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


# --- AI answers: recorded per row, replayed in later runs ---------------------------------------------------------

class Recorder:
    def __init__(self, provider: str | None, live: bool):
        self.provider, self.live = provider, live
        self.path = RESULTS / f"ai_{provider}.json"
        self.answers: dict = json.loads(self.path.read_text(encoding="utf-8")) if provider and self.path.exists() else {}
        self.live_requests = self.replayed = self.not_recorded = 0

    async def parse_rows(self, rows, stats: dict) -> list[dict]:
        if not self.provider:
            raise RuntimeError("rules only: no AI")
        known = [r for r in rows if r.ai_text in self.answers]
        missing = [r for r in rows if r.ai_text not in self.answers]
        self.replayed += len(known)
        items = [{**self.answers[r.ai_text], "row": r.row} for r in known if self.answers[r.ai_text]]
        if missing and not self.live:
            self.not_recorded += len(missing)
            raise RuntimeError(f"{len(missing)} rows have no recorded answer (run with --live)")
        if missing:
            before = stats.get("requests", 0)
            got = {it["row"]: it for it in await self._ask(missing, stats)}
            self.live_requests += stats.get("requests", 0) - before
            for r in missing:
                item = got.get(r.row)
                self.answers[r.ai_text] = {k: v for k, v in item.items() if k != "row"} if item else None
            items += list(got.values())
            self.save()
        return items

    async def _ask(self, rows, stats: dict) -> list[dict]:
        if self.provider == "gemini":
            return await ai_parser._split_on_truncation(ai_parser._gemini, rows, stats)
        result, size = [], settings.groq_chunk_rows
        for start in range(0, len(rows), size):
            result += await ai_parser._split_on_truncation(ai_parser._groq, rows[start : start + size], stats)
        return result

    def save(self) -> None:
        RESULTS.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(self.answers, ensure_ascii=False, indent=0), encoding="utf-8")


# --- datasets ---------------------------------------------------------------------------------------------------

def _tokens(text: str | None) -> set[str]:
    return set(cache_key(text or "").split())


def _match(labels: list[dict], rows: list[dict]) -> tuple[list[tuple[dict, dict | None]], list[dict]]:
    """Label -> parsed row by the words of the source text (most of the label words must be in the row)."""
    pairs, used = [], set()
    scored = []
    for li, lab in enumerate(labels):
        words = _tokens(lab["text"])
        for ri, row in enumerate(rows):
            have = _tokens(f"{row['raw_name']} {row.get('section') or ''}")
            score = len(words & have) / max(1, len(words))
            if score >= 0.8:
                scored.append((score, li, ri))
    by_label: dict[int, int] = {}
    for score, li, ri in sorted(scored, reverse=True):
        if li not in by_label and ri not in used:
            by_label[li] = ri
            used.add(ri)
    pairs = [(lab, rows[by_label[i]] if i in by_label else None) for i, lab in enumerate(labels)]
    return pairs, [r for i, r in enumerate(rows) if i not in used]


async def _parse(rows, stats):
    with _empty_db() as db:
        return await parse_clean_rows(db, rows, stats)


def run_files(recorder: Recorder) -> list[dict]:
    meta = json.loads((BENCH / "synthetic" / "files.json").read_text(encoding="utf-8"))
    out = []
    for name, info in meta.items():
        path = BENCH / "synthetic" / info["file"]
        labels = json.loads((BENCH / "synthetic" / f"{name}.json").read_text(encoding="utf-8"))
        started = time.monotonic()
        rows = clean_markdown(file_to_markdown(path.read_bytes(), path.name))
        stats: dict = {}
        parsed = asyncio.run(_parse(rows, stats))
        stats["seconds"] = round(time.monotonic() - started, 1)
        pairs, extra = _match(labels, parsed)
        out.append({"dataset": name, "kind": "synthetic", "currency": info["currency"], "stats": stats,
                    "pairs": pairs, "extra": extra})
    return out


def run_gshop(recorder: Recorder) -> list[dict]:
    if not GSHOP.exists():
        print("Gshop file not found, skipped")
        return []
    data = json.loads((BENCH / "gshop" / "labels.json").read_text(encoding="utf-8"))
    labels = [{**lab, "currency": data["currency"]} for lab in data["items"]]
    started = time.monotonic()
    rows = clean_markdown(file_to_markdown(GSHOP.read_bytes(), GSHOP.name))
    # Only the labelled sample is parsed (the AI budget); rows are found by the words of the label and the price
    wanted = []
    for r in rows:
        have = _tokens(" ".join(r.cells))
        if any(len(_tokens(lab["text"]) & have) / max(1, len(_tokens(lab["text"]))) >= 0.8
               and r.price == lab["price"] for lab in labels):
            wanted.append(r)
    stats: dict = {"file_rows": len(rows)}
    parsed = asyncio.run(_parse(wanted, stats))
    stats["seconds"] = round(time.monotonic() - started, 1)
    pairs, extra = _match(labels, parsed)
    return [{"dataset": "gshop", "kind": "gshop", "currency": data["currency"], "stats": stats, "pairs": pairs,
             "extra": extra}]


def run_posts(recorder: Recorder) -> list[dict]:
    posts = json.loads((BENCH / "posts" / "posts.json").read_text(encoding="utf-8"))["posts"]
    started = time.monotonic()
    all_rows, owner, reasons = [], {}, {}
    for p in posts:
        rows = text_import.text_to_rows(p["text"])
        if not rows:
            reasons[p["id"]] = text_import.no_rows_reason(p["text"])
        for r in rows:
            r.row = len(all_rows) + 1  # one AI request for all posts: ids must be unique
            owner[r.row] = p["id"]
            all_rows.append(r)
    stats: dict = {}
    parsed = asyncio.run(_parse(all_rows, stats))
    stats["seconds"] = round(time.monotonic() - started, 1)
    by_post: dict[str, list] = {}
    for row in parsed:
        by_post.setdefault(owner[row["row"]], []).append(row)
    pairs, extra, no_model = [], [], []
    for p in posts:
        rows = by_post.get(p["id"], [])
        if p["expected"] == "no_model":
            no_model.append({"id": p["id"], "rows": len(rows), "reason": None if rows else reasons.get(p["id"])})
            continue
        free = list(rows)
        for exp in p["expected"]:
            # The same price first, otherwise the next row in order
            row = next((r for r in free if r["price"] == exp["price"]), free[0] if free else None)
            if row:
                free.remove(row)
            pairs.append(({**exp, "id": p["id"], "source": p["source"]}, row))
        extra += free
    return [{"dataset": "posts", "kind": "posts", "currency": "UZS", "stats": stats, "pairs": pairs,
             "extra": extra, "no_model": no_model}]


# --- scoring ----------------------------------------------------------------------------------------------------

def _alnum(text) -> str:
    return re.sub(r"[^a-zа-я0-9]", "", str(text or "").lower().replace("ё", "е"))


def _brand(value) -> str:
    return _alnum(canonical_brand(value) if value else "")


def _same_value(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 1e-6
    return _alnum(a) == _alnum(b)


def score_field(field: str, lab: dict, row: dict | None, currency: str):
    """(scored?, filled?, correct?)."""
    want = lab.get(field)
    if field == "model" and not want:
        return False, False, False
    if row is None:
        return True, False, False
    got = row.get(field)
    if field == "currency":
        got = row.get("currency") or currency
    if field == "brand":
        return True, bool(got), _brand(got) == _brand(want)
    if field == "model":
        # The model may be named by its series and number or by the part number: both are right if written
        # in the clean source row ("ROG STRIX Z890-A GAMING WIFI" or "90MB1I90-M0EAY0")
        a, b = _alnum(want), _alnum(got)
        alt = [_alnum(x) for x in (lab.get("name"), lab.get("source"), lab.get("article")) if x]
        ok = bool(b) and (a in b or (len(b) >= 3 and b in a)
                          or (len(b) >= 4 and re.search(r"\d", b) is not None and any(b in x for x in alt)))
        return True, bool(got), ok
    if field == "price":
        return True, got is not None, got is not None and abs(got - want) <= 0.005 * want
    return True, got is not None, got == want


def check_flags(lab: dict, row: dict | None, currency: str, market: dict) -> dict:
    expected = set(lab.get("flags") or [])
    if row is None:
        return {"expected": sorted(expected), "found": [], "info": []}
    full = {**row, "currency": row.get("currency") or currency}
    key = make_match_key(row.get("category") or "other", row["name"], row.get("brand"), row.get("specs"))
    flags = check_offer(full, market.get(key), RATE)
    found = {f["type"] for f in flags if f["level"] != "info"} | ({"typo"} if (row.get("specs") or {}).get(SUSPECT) else set())
    info = {f["type"] for f in flags if f["level"] == "info"}
    return {"expected": sorted(expected), "found": sorted(found), "info": sorted(info)}


def score(results: list[dict]) -> dict:
    market = json.loads((BENCH / "synthetic" / "market.json").read_text(encoding="utf-8"))
    completions = completion_index(market)  # every reference card of the synthetic set, as in a catalog
    summary = {}
    for res in results:
        fields = {f: {"scored": 0, "filled": 0, "correct": 0} for f in (*FIELDS, "card")}
        # guessed = AI values not found in the row: cut by the check (with the label: right / wrong / unknown key)
        specs = {"keys": 0, "correct": 0, "wrong": 0, "missing": 0, "extra": 0, "ai_values": 0,
                 "guessed": 0, "guessed_right": 0, "guessed_wrong": 0}
        traps = {"total": 0, "caught": 0, "by_type": {}}
        clean = {"rows": 0, "false_flags": 0, "info_flags": 0}
        errors = []
        for lab, row in res["pairs"]:
            for f in FIELDS:
                scored, filled, correct = score_field(f, lab, row, res["currency"])
                if scored:
                    fields[f]["scored"] += 1
                    fields[f]["filled"] += filled
                    fields[f]["correct"] += correct
                    if not correct and len(errors) < 400:
                        errors.append({"id": lab.get("id"), "field": f, "text": lab["text"] if "text" in lab else lab.get("model"),
                                       "want": lab.get(f), "got": (row or {}).get(f) if f != "currency" or not row else (row.get("currency") or res["currency"])})
            if lab.get("match_key"):
                fields["card"]["scored"] += 1
                if row:
                    key = make_match_key(row.get("category") or "other", row["name"], row.get("brand"), row.get("specs"))
                    key = key if key in market else unique_completion(key, completions) or key  # as publishing does
                    fields["card"]["filled"] += 1
                    fields["card"]["correct"] += key == lab["match_key"]
                    if key != lab["match_key"] and len(errors) < 400:
                        errors.append({"id": lab.get("id"), "field": "card", "text": lab["text"], "want": lab["match_key"], "got": key})
            got_specs = {k: v for k, v in ((row or {}).get("specs") or {}).items() if not k.startswith("_") and k != "brand"}
            want_specs = {k: v for k, v in (lab.get("specs") or {}).items() if k != "brand"}
            for k, v in want_specs.items():
                specs["keys"] += 1
                if k not in got_specs:
                    specs["missing"] += 1
                elif _same_value(got_specs[k], v):
                    specs["correct"] += 1
                else:
                    specs["wrong"] += 1
                    if len(errors) < 400:
                        errors.append({"id": lab.get("id"), "field": f"spec:{k}", "text": lab.get("text"), "want": v, "got": got_specs[k]})
            if row is not None:
                specs["extra"] += sum(1 for k in got_specs if k not in want_specs)
                category = row.get("category") or "other"
                guesses = {k: v for k, v in (row.get("specs_guess") or {}).items() if k != "brand"}
                specs["guessed"] += len(guesses)
                specs["ai_values"] += len(guesses) + (len(got_specs) if row.get("source") in ("ai", "cache") else 0)
                for k, v in guesses.items():
                    if k in want_specs:
                        value = normalize_specs(category, "", {k: v}).get(k)
                        specs["guessed_right" if _same_value(value, want_specs[k]) else "guessed_wrong"] += 1
            fl = check_flags(lab, row, res["currency"], market)
            if fl["expected"]:
                traps["total"] += 1
                hit = set(fl["expected"]) <= set(fl["found"]) | set(fl["info"])
                traps["caught"] += hit
                for t in fl["expected"]:
                    b = traps["by_type"].setdefault(t, [0, 0])
                    b[0] += 1
                    b[1] += t in fl["found"] or t in fl["info"]
                if not hit:
                    errors.append({"id": lab.get("id"), "field": "flags", "text": lab.get("text"), "want": fl["expected"], "got": fl["found"] + fl["info"]})
            elif row is not None:
                clean["rows"] += 1
                clean["false_flags"] += bool(fl["found"])
                clean["info_flags"] += bool(fl["info"])
                if fl["found"]:
                    errors.append({"id": lab.get("id"), "field": "false_flag", "text": lab.get("text"), "want": [], "got": fl["found"]})
        st = res["stats"]
        item = {
            "kind": res["kind"], "labels": len(res["pairs"]), "matched": sum(r is not None for _, r in res["pairs"]),
            "extra_rows": len(res["extra"]), "fields": fields, "specs": specs, "traps": traps, "clean": clean,
            "stats": {k: st.get(k) for k in ("rows", "rule", "cache", "ai_rows", "requests", "failed_rows", "seconds",
                                             "splits", "models", "groq_requests")},
            "extra": [{"raw_name": r["raw_name"][:120], "name": r["name"], "price": r["price"]} for r in res["extra"][:30]],
            "errors": errors,
        }
        if "no_model" in res:
            item["no_model"] = res["no_model"]
        summary[res["dataset"]] = item
    return summary


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:5.1f}" if b else "    -"


def print_summary(summary: dict, config: str) -> None:
    print(f"\n=== {config} ===")
    head = f"{'dataset':15} {'rows':>5} {'found':>5}" + "".join(f" {f[:8]:>8}" for f in (*FIELDS, "card")) + "   specs  traps  falseF  extra req   sec"
    print(head)
    for name, s in summary.items():
        line = f"{name:15} {s['labels']:5} {s['matched']:5}"
        for f in (*FIELDS, "card"):
            v = s["fields"][f]
            line += f" {pct(v['correct'], v['scored']):>8}"
        sp, tr, cl, st = s["specs"], s["traps"], s["clean"], s["stats"]
        line += f"  {pct(sp['correct'], sp['keys'])}  {tr['caught']:2}/{tr['total']:<2} {cl['false_flags']:3}/{cl['rows']:<4}"
        line += f" {s['extra_rows']:4} {st.get('requests') or 0:3} {st.get('seconds') or 0:5}"
        print(line)
        if "no_model" in s:
            print("   no-model posts:", s["no_model"])


def suite(args) -> None:
    provider = PROVIDERS[args.config]
    recorder = Recorder(provider, args.live)
    ai_parser.parse_rows = recorder.parse_rows  # importer imported the name: patch there too
    importer.parse_rows = recorder.parse_rows
    if args.config == "gemini_nocheck":
        importer.split_specs = lambda specs, text: (specs, {})
    if provider == "groq":
        settings.parser_chunk_rows = settings.groq_chunk_rows * 7  # Groq gets its own 60-row pieces inside
    started = time.monotonic()
    results = []
    for name in args.datasets.split(","):
        results += {"synthetic": run_files, "gshop": run_gshop, "posts": run_posts}[name](recorder)
    summary = score(results)
    summary["_run"] = {"config": args.config, "tag": args.tag, "live_requests": recorder.live_requests,
                       "replayed_rows": recorder.replayed, "not_recorded_rows": recorder.not_recorded,
                       "seconds": round(time.monotonic() - started, 1), "date": time.strftime("%Y-%m-%d %H:%M")}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{args.config}_{args.tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print_summary({k: v for k, v in summary.items() if not k.startswith("_")}, args.config)
    print(summary["_run"])


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "suite":
        ap = argparse.ArgumentParser()
        ap.add_argument("suite")
        ap.add_argument("--config", choices=list(PROVIDERS), default="rules")
        ap.add_argument("--datasets", default="synthetic,gshop,posts")
        ap.add_argument("--tag", default="run")
        ap.add_argument("--live", action="store_true")
        suite(ap.parse_args())
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--tokens", action="store_true")
    ap.add_argument("--live", action="store_true")
    file_report(ap.parse_args())


if __name__ == "__main__":
    main()
