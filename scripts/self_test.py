#!/usr/bin/env python3
"""Fast repeatable smoke/regression test for the installed corpus helpers."""
import csv
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON = sys.executable


def run(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout


def main():
    outcomes = []
    def check(name, condition, detail=''):
        outcomes.append({'test': name, 'passed': bool(condition), 'detail': detail})

    skill=(HERE.parent/'SKILL.md').read_text(encoding='utf-8')
    front=re.match(r'^---\r?\n(.*?)\r?\n---',skill,re.S)
    name=re.search(r'(?m)^name:\s*([a-z0-9-]+)\s*$',front.group(1) if front else '')
    description=re.search(r'(?m)^description:\s*"(.+)"\s*$',front.group(1) if front else '')
    check('skill frontmatter',bool(front and name and description and len(name.group(1))<=64 and len(description.group(1))<=1024))
    check('no unfinished placeholder',not re.search(r'(?m)^\s*\[TODO:',skill))
    check('required resources',all((HERE.parent/path).exists() for path in ['references/document-workflow.md','references/corpus-workflow.md','scripts/corpus_inventory.py','scripts/corpus_screen.py','scripts/environment_check.py','scripts/ocr_pdf.py']))

    with tempfile.TemporaryDirectory(prefix='academic-skill-test-') as temp:
        root = Path(temp); source = root/'source'; reports = root/'reports'; unique = root/'unique'
        source.mkdir()
        common = 'Title: Rural digital learning\nAuthor: Sari\nYear: 2024\nDOI: 10.1234/test(2024)\nEvidence.'
        (source/'a.txt').write_text(common, encoding='utf-8')
        (source/'a-copy.txt').write_text(common, encoding='utf-8')
        (source/'version.txt').write_text(common+' Revised.', encoding='utf-8')
        (source/'reference-only.txt').write_text('Title: Different study\nAuthor: Budi\nYear: 2025\nReferences:\n10.1234/test(2024)', encoding='utf-8')
        (source/'unsupported.png').write_bytes(b'fixture')
        summary = json.loads(run([PYTHON, str(HERE/'corpus_inventory.py'), str(source), '--report-dir', str(reports), '--copy-exact-unique-to', str(unique)]))
        check('exact duplicate', summary['exact_duplicate_extra_copies']==1)
        check('bibliographic candidate', summary['bibliographic_candidate_groups']==1)
        check('reference DOI ignored', next(csv.DictReader((reports/'inventory.csv').open(encoding='utf-8-sig')))['doi']=='10.1234/test(2024)')
        inventory=list(csv.DictReader((reports/'inventory.csv').open(encoding='utf-8-sig')))
        reference=next(row for row in inventory if row['relative_path']=='reference-only.txt')
        check('reference-only DOI absent', reference['doi']=='')
        check('unsupported counted', summary['unsupported_files']==1)
        manifest=list(csv.DictReader((reports/'copy_manifest.csv').open(encoding='utf-8-sig')))
        check('copy manifest', bool(manifest) and all(row['status'].startswith('verified') for row in manifest))
        rerun=json.loads(run([PYTHON, str(HERE/'corpus_inventory.py'), str(source), '--report-dir', str(reports), '--copy-exact-unique-to', str(unique)]))
        check('resume cache', rerun['metadata_reused_by_hash']==4)
        review=root/'review.csv'
        run([PYTHON, str(HERE/'corpus_screen.py'), '--reports', str(reports), '--review', str(review)])
        rows=list(csv.DictReader(review.open(encoding='utf-8-sig')))
        for row in rows:
            row['decision']='include' if row['relative_path']=='a.txt' else 'exclude'
            row['reason']='Eligible fixture' if row['decision']=='include' else 'Fixture excluded'
            if row['decision']=='include': row['read_scope']='entire text'; row['evidence_location']='whole fixture'
        with review.open('w',newline='',encoding='utf-8-sig') as handle:
            writer=csv.DictWriter(handle,fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
        selected=root/'selected'
        selection=json.loads(run([PYTHON, str(HERE/'corpus_screen.py'), '--reports', str(reports), '--review', str(review), '--selected', str(selected)]))
        check('review export', selection['status']=='complete' and selection['selected_unique']==1)
    result={'passed':all(item['passed'] for item in outcomes),'tests':outcomes}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
