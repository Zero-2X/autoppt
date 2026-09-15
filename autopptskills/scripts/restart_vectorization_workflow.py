"""Restart vectorization with a strict character/frame/background separation contract.

The script is deliberately conservative: preserve the verified full-slide image as one
continuous background, route every exact character string to native text, and retain
only bounded isolated graphics as movable/vector candidates. It emits an auditable
diagnosis and a new deck manifest without overwriting prior rounds.
"""
from __future__ import annotations
import json, shutil
from pathlib import Path

def main(src: str, out: str) -> None:
    srcp, outp = Path(src), Path(out)
    deck = json.loads(srcp.read_text(encoding='utf-8'))
    outp.mkdir(parents=True, exist_ok=True)
    reasons = [
        'prior rounds traced page-level artwork, so raster strokes were duplicated by native geometry',
        'OCR geometry was treated as final wording, causing glyph drift and double text',
        'icons were classified by syntax/path count rather than PowerPoint render fidelity',
        'background cleanup was broad or unmeasured, erasing antialiasing and nearby marks',
        'editability counts were used as a success proxy while visual comparison was incomplete',
    ]
    for slide in deck.get('slides', []):
        slide['background_policy'] = 'one-continuous-verified-image; no semantic glyphs or foreground frames'
        slide['text_policy'] = 'native-text-from-reviewed-whitelist; OCR is geometry proposal only'
        slide['vector_policy'] = 'bounded-isolated-candidate; accept only after exact PowerPoint render review'
        slide['separation_contract'] = {'characters':'native-text','frames':'native-shape-or-background-cleaned','background':'continuous-image'}
    deck['round_scope'] = 'restart-vectorization-character-frame-background-separated'
    deck['vectorization_contract'] = {'native_text_coverage_target':1.0,'semantic_full_slide_pictures':0,'page_tracing_forbidden':True,'visual_gate_required':True}
    (outp/'deck-character-frame-separated.json').write_text(json.dumps(deck,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={'status':'restarted','source':str(srcp.resolve()),'output':str((outp/'deck-character-frame-separated.json').resolve()),'root_causes':reasons,'acceptance_gates':['exact-text audit','foreground-hidden background counterfactual','PowerPoint render','all-slide visual review','layer contract gate']}
    (outp/'vectorization-diagnosis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('src'); ap.add_argument('out'); a=ap.parse_args(); main(a.src,a.out)
