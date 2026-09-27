#!/usr/bin/env python3
"""Report runtime readiness for corpus, PDF, DOCX, OCR, and skill validation."""
import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path


def module(name):
    return importlib.util.find_spec(name) is not None


def executable(*names):
    return next((shutil.which(name) for name in names if shutil.which(name)), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require', action='append', choices=['corpus', 'pdf-read', 'pdf-render', 'docx-read', 'docx-render', 'ocr', 'skill-validator'], default=[])
    parser.add_argument('--json-out', type=Path)
    args = parser.parse_args()
    dependencies=Path(sys.executable).resolve().parent.parent
    tesseract_js=dependencies/'node/node_modules/tesseract.js/package.json'
    checks = {
        'corpus': {'ready': True, 'detail': f'Python {sys.version.split()[0]}'},
        'pdf-read': {'ready': module('pypdf'), 'detail': 'pypdf'},
        'pdf-render': {'ready': bool(executable('pdftoppm', 'pdftoppm.exe')), 'detail': executable('pdftoppm', 'pdftoppm.exe') or 'pdftoppm unavailable'},
        'docx-read': {'ready': module('docx'), 'detail': 'python-docx plus OOXML extraction'},
        'docx-render': {'ready': bool(executable('soffice', 'soffice.exe')), 'detail': executable('soffice', 'soffice.exe') or 'LibreOffice soffice unavailable'},
        'ocr': {'ready': bool(executable('tesseract', 'tesseract.exe')) or tesseract_js.exists(), 'detail': executable('tesseract', 'tesseract.exe') or (str(tesseract_js.parent) if tesseract_js.exists() else 'Tesseract unavailable')},
        'skill-validator': {'ready': module('yaml'), 'detail': 'PyYAML' if module('yaml') else 'PyYAML unavailable'},
    }
    missing = [name for name in args.require if not checks[name]['ready']]
    result = {'checks': checks, 'required': args.require, 'missing_required': missing, 'ready': not missing}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding='utf-8')
    print(rendered)
    return 0 if not missing else 2


if __name__ == '__main__':
    raise SystemExit(main())
