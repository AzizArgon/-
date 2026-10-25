"""Tables (Markdown) and charts (PNG) for docs/experiment.md from tests/benchmark/results/*.json.

Usage (from backend/): .venv/Scripts/python.exe tests/benchmark/report.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RESULTS = Path(__file__).parent / "results"
OUT = Path(__file__).resolve().parents[3] / "docs" / "experiment"
FIELDS = ("category", "brand", "model", "price", "currency", "condition", "card")
NAMES = {"s1_slang": "Сленг", "s2_typos": "Опечатки", "s3_columns": "Столбцы", "s4_merged": "Объед.\nячейки",
         "s5_multitable": "Неск.\nтаблиц", "s6_csv_cp1251": "CSV cp1251", "s7_pdf": "PDF", "gshop": "Gshop",
         "posts": "Посты"}
# Validated categorical palette (dataviz skill, light surface), fixed order: blue, orange, aqua, yellow
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
INK, MUTED, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"


def load(name: str) -> dict:
    return json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))


def pct(a, b) -> float | None:
    return 100 * a / b if b else None


def fmt(v) -> str:
    return "—" if v is None else f"{v:.1f}"


def datasets(run: dict) -> list[str]:
    return [k for k in run if not k.startswith("_")]


def field_table(run: dict) -> str:
    head = "| Набор | Строк | Найдено | Категория | Бренд | Модель | Цена | Валюта | Состояние | Карточка | Характ. | Не заполнено характ. |"
    lines = [head, "|" + "---|" * 13]
    for ds in datasets(run):
        s = run[ds]
        cells = [fmt(pct(s["fields"][f]["correct"], s["fields"][f]["scored"])) for f in FIELDS]
        sp = s["specs"]
        lines.append(f"| {NAMES[ds].replace(chr(10), " ")} | {s['labels']} | {s['matched']} | " + " | ".join(cells)
                     + f" | {fmt(pct(sp['correct'], sp['keys']))} | {fmt(pct(sp['missing'], sp['keys']))} |")
    return "\n".join(lines)


def totals(run: dict, kinds=None) -> dict:
    t = {f: [0, 0, 0] for f in FIELDS}
    sp = {"keys": 0, "correct": 0, "missing": 0, "wrong": 0, "extra": 0, "guessed": 0, "guessed_right": 0,
          "guessed_wrong": 0, "ai_values": 0}
    af = {"traps": 0, "caught": 0, "clean": 0, "false": 0, "info": 0}
    st = {"rows": 0, "rule": 0, "cache": 0, "ai_rows": 0, "requests": 0, "seconds": 0.0, "failed_rows": 0}
    for ds in datasets(run):
        s = run[ds]
        if kinds and s["kind"] not in kinds:
            continue
        for f in FIELDS:
            v = s["fields"][f]
            t[f][0] += v["correct"]
            t[f][1] += v["filled"]
            t[f][2] += v["scored"]
        for k in sp:
            sp[k] += s["specs"].get(k, 0)
        af["traps"] += s["traps"]["total"]
        af["caught"] += s["traps"]["caught"]
        af["clean"] += s["clean"]["rows"]
        af["false"] += s["clean"]["false_flags"]
        af["info"] += s["clean"]["info_flags"]
        for k in st:
            st[k] += s["stats"].get(k) or 0
    return {"fields": t, "specs": sp, "af": af, "stats": st}


def config_table(runs: dict[str, dict], kinds=None) -> str:
    lines = ["| Показатель | " + " | ".join(runs) + " |", "|---|" + "---|" * len(runs)]
    tot = {name: totals(r, kinds) for name, r in runs.items()}
    labels = {"category": "Категория", "brand": "Бренд", "model": "Модель", "price": "Цена", "currency": "Валюта",
              "condition": "Состояние", "card": "Попадание в эталонную карточку"}
    for f in FIELDS:
        vals = [fmt(pct(t["fields"][f][0], t["fields"][f][2])) for t in tot.values()]
        lines.append(f"| {labels[f]}, % верных | " + " | ".join(vals) + " |")
    lines.append("| Характеристики, % верных из размеченных | "
                 + " | ".join(fmt(pct(t["specs"]["correct"], t["specs"]["keys"])) for t in tot.values()) + " |")
    lines.append("| Характеристики с неверным значением | " + " | ".join(str(t["specs"]["wrong"]) for t in tot.values()) + " |")
    lines.append("| Лишние характеристики (нет в разметке) | " + " | ".join(str(t["specs"]["extra"]) for t in tot.values()) + " |")
    lines.append("| Anti-Fraud: поймано подвохов | "
                 + " | ".join(f"{t['af']['caught']} из {t['af']['traps']}" for t in tot.values()) + " |")
    lines.append("| Anti-Fraud: ложные флаги (warning/danger) на чистых строках | "
                 + " | ".join(f"{t['af']['false']} из {t['af']['clean']}" for t in tot.values()) + " |")
    lines.append("| Строк: правилами / ИИ | " + " | ".join(f"{t['stats']['rule']} / {t['stats']['ai_rows']}" for t in tot.values()) + " |")
    lines.append("| Не распознано (без ИИ или сбой) | " + " | ".join(str(t["stats"]["failed_rows"]) for t in tot.values()) + " |")
    return "\n".join(lines)


def _style(ax, title: str, ylabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=12)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#d8d7d2")
    ax.grid(axis="y", color="#ecebe7", linewidth=0.8)
    ax.set_axisbelow(True)


def grouped(series: dict[str, list[float | None]], cats: list[str], title: str, ylabel: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    n = len(series)
    width = 0.8 / n
    for i, (name, vals) in enumerate(series.items()):
        xs = [x + (i - (n - 1) / 2) * width for x in range(len(cats))]
        ax.bar(xs, [v or 0 for v in vals], width=width - 0.02, color=COLORS[i], label=name, edgecolor=SURFACE,
               linewidth=1)
    ax.set_xticks(range(len(cats)), cats)
    ax.set_ylim(0, 105)
    _style(ax, title, ylabel)
    ax.legend(frameon=False, fontsize=9, loc="upper left", ncols=n, bbox_to_anchor=(0, -0.13))
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    after = {"Только правила": load("rules_after"), "Правила + Gemini": load("gemini_after"),
             "Правила + Groq": load("groq_after"), "Gemini без проверки характ.": load("gemini_nocheck_after")}
    before = {"Только правила": load("rules_before"), "Правила + Gemini": load("gemini_before")}
    out = ["## Конфигурации (после исправлений), все наборы", config_table(after)]
    for kinds, title in ((("synthetic",), "синтетика"), (("gshop",), "Gshop"), (("posts",), "посты")):
        out += [f"## Конфигурации — {title}", config_table(after, kinds)]
    out += ["## До / после исправлений (все наборы)", config_table({f"{k} — до": v for k, v in before.items()}
                                                                   | {f"{k} — после": after[k] for k in before})]
    for name in ("rules_before", "gemini_before", "rules_after", "gemini_after", "groq_after"):
        out += [f"## По наборам: {name}", field_table(load(name))]
    g = after["Правила + Gemini"]
    out.append("## Нет модели в посте: " + json.dumps(g["posts"].get("no_model"), ensure_ascii=False))
    for name, run in after.items():
        out.append(f"## Запуск {name}: " + json.dumps(run["_run"], ensure_ascii=False))
    (RESULTS / "tables.md").write_text("\n\n".join(out) + "\n", encoding="utf-8")

    # Figure 1: card matching by dataset and configuration
    cats = [NAMES[d] for d in datasets(g) if g[d]["fields"]["card"]["scored"]]
    keys = [d for d in datasets(g) if g[d]["fields"]["card"]["scored"]]
    grouped({name: [pct(r[d]["fields"]["card"]["correct"], r[d]["fields"]["card"]["scored"]) for d in keys]
             for name, r in list(after.items())[:3]}, cats,
            "Строки, попавшие в правильную эталонную карточку", "%", OUT / "fig1_cards_by_config.png")
    # Figure 2: before / after with Gemini — share of correct fields (mean of the 6 fields) by dataset
    def mean_fields(run, d):
        vals = [pct(run[d]["fields"][f]["correct"], run[d]["fields"][f]["scored"]) for f in FIELDS[:6]]
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None
    all_ds = datasets(g)
    grouped({"До исправлений": [mean_fields(before["Правила + Gemini"], d) for d in all_ds],
             "После исправлений": [mean_fields(g, d) for d in all_ds]}, [NAMES[d] for d in all_ds],
            "Правила + Gemini: средняя доля верных полей, до и после исправлений", "%",
            OUT / "fig2_before_after.png")
    # Figure 3: price and currency read by code, before / after (rules only, no AI)
    rb, ra = before["Только правила"], after["Только правила"]
    grouped({"Цена — до": [pct(rb[d]["fields"]["price"]["correct"], rb[d]["fields"]["price"]["scored"]) for d in all_ds],
             "Цена — после": [pct(ra[d]["fields"]["price"]["correct"], ra[d]["fields"]["price"]["scored"]) for d in all_ds],
             "Валюта — до": [pct(rb[d]["fields"]["currency"]["correct"], rb[d]["fields"]["currency"]["scored"]) for d in all_ds],
             "Валюта — после": [pct(ra[d]["fields"]["currency"]["correct"], ra[d]["fields"]["currency"]["scored"]) for d in all_ds]},
            [NAMES[d] for d in all_ds], "Цена и валюта, которые берёт код (без ИИ): до и после", "%",
            OUT / "fig3_price_currency_code.png")
    print((RESULTS / "tables.md").read_text(encoding="utf-8")[:6000])


if __name__ == "__main__":
    main()
