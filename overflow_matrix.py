from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND = ROOT.parent / "PrintHub-ZPL-ll"
sys.path.insert(0, str(BACKEND))

from zplgrid import LabelTarget, compile_zpl  # noqa: E402
from zplgrid.labelary import lint_labelary_zpl, render_labelary_png  # noqa: E402


TARGET = LabelTarget(width_mm=74.0, height_mm=26.0, dpi=203)
TEXTS = {
    "long_word": "A" * 50,
    "words": "Alpha bravo charlie delta echo foxtrot golf hotel india juliet",
    "explicit": "FIRST LINE\nSECOND LINE\nTHIRD LINE",
    "reported_variables": "{_counter_daily} {name} " + "a" * 19 + " " + "d" * 13,
}


def template(*, text: str, fit: str, wrap: str, max_lines: int, align_h: str, align_v: str) -> dict:
    return {
        "schema_version": 1,
        "name": "overflow-matrix",
        "defaults": {"leaf_padding_mm": [1.0, 1.0, 1.0, 1.0]},
        "layout": {
            "kind": "leaf",
            "elements": [
                {
                    "type": "text",
                    "text": text,
                    "font_height_mm": 4.0,
                    "font_width_mm": 4.0,
                    "fit": fit,
                    "wrap": wrap,
                    "max_lines": max_lines,
                    "align_h": align_h,
                    "align_v": align_v,
                }
            ],
        },
    }


CASES = [
    ("reported_char_center_m2", "long_word", "wrap", "char", 2, "center", "top"),
    ("reported_word_center_m2", "long_word", "wrap", "word", 2, "center", "top"),
    ("char_left_m1", "long_word", "wrap", "char", 1, "left", "top"),
    ("char_left_m2", "long_word", "wrap", "char", 2, "left", "top"),
    ("char_left_m3", "long_word", "wrap", "char", 3, "left", "top"),
    ("char_right_m2", "long_word", "wrap", "char", 2, "right", "top"),
    ("word_left_m1", "words", "wrap", "word", 1, "left", "top"),
    ("word_left_m2", "words", "wrap", "word", 2, "left", "top"),
    ("word_left_m3", "words", "wrap", "word", 3, "left", "top"),
    ("truncate_word_m2", "words", "truncate", "word", 2, "left", "top"),
    ("shrink_word_m2", "words", "shrink_to_fit", "word", 2, "center", "center"),
    ("shrink_char_m2", "long_word", "shrink_to_fit", "char", 2, "center", "center"),
    ("explicit_wrap_m2", "explicit", "wrap", "word", 2, "left", "top"),
    ("explicit_truncate_m2", "explicit", "truncate", "word", 2, "left", "top"),
    ("explicit_shrink_m2", "explicit", "shrink_to_fit", "word", 2, "left", "top"),
    ("overflow_long", "long_word", "overflow", "none", 1, "left", "top"),
    ("reported_center_shrink_m2", "reported_variables", "shrink_to_fit", "word", 2, "center", "center"),
]


def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    output = ROOT / "artifacts" / "overflow" / phase
    output.mkdir(parents=True, exist_ok=True)
    summary: list[dict] = []
    for name, text_name, fit, wrap, max_lines, align_h, align_v in CASES:
        zpl = compile_zpl(
            template(
                text=TEXTS[text_name],
                fit=fit,
                wrap=wrap,
                max_lines=max_lines,
                align_h=align_h,
                align_v=align_v,
            ),
            target=TARGET,
            variables={"_counter_daily": 0, "name": "Nathaniel"},
        )
        (output / f"{name}.zpl").write_text(zpl, encoding="utf-8")
        render_labelary_png(
            zpl=zpl,
            out_path=output / f"{name}.png",
            dpmm=8,
            label_width_in=TARGET.width_mm / 25.4,
            label_height_in=TARGET.height_mm / 25.4,
        )
        warnings = [warning.__dict__ for warning in lint_labelary_zpl(
            zpl,
            dpmm=8,
            label_width_in=TARGET.width_mm / 25.4,
            label_height_in=TARGET.height_mm / 25.4,
        )]
        summary.append({"name": name, "fit": fit, "wrap": wrap, "max_lines": max_lines, "warnings": warnings})
        print(name)
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
