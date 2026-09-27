#!/usr/bin/env python3
"""Prepare a review ledger, then export explicitly reviewed include decisions.

This tool does not decide academic relevance. Agents fill the ledger from sources.
"""
import argparse
import csv
import json
from pathlib import Path
from corpus_inventory import file_hash, copy_verified, write_csv, atomic_json

REVIEW=['relative_path','sha256','decision','reason','read_scope','evidence_location','study_family','quality_notes']

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reports',type=Path,required=True)
    p.add_argument('--review',type=Path,required=True)
    p.add_argument('--selected',type=Path)
    args=p.parse_args()
    reports=args.reports.resolve(); review=args.review.resolve()
    summary=json.loads((reports/'summary.json').read_text(encoding='utf-8'))
    if not summary.get('status','').startswith('complete'): p.error('Inventory has not completed')
    source=Path(summary['source']).resolve()
    if review==source or source in review.parents: p.error('Review ledger cannot be inside source')
    inventory=list(csv.DictReader((reports/'inventory.csv').open(encoding='utf-8-sig')))
    if not args.selected:
        if review.exists(): p.error('Review ledger exists; will not overwrite decisions')
        review.parent.mkdir(parents=True,exist_ok=True)
        write_csv(review,REVIEW,[dict(relative_path=r['relative_path'],sha256=r['sha256'],decision='pending',reason='',read_scope='',evidence_location='',study_family='',quality_notes='') for r in inventory])
        print(json.dumps({'prepared':len(inventory),'review':str(review)})); return
    selected=args.selected.resolve()
    if selected==source or selected in source.parents or source in selected.parents: p.error('Selected folder overlaps source')
    if selected==reports or selected in reports.parents or reports in selected.parents: p.error('Selected folder overlaps reports')
    indexed={r['relative_path']:r for r in inventory}
    reviews=list(csv.DictReader(review.open(encoding='utf-8-sig')))
    if len({r['relative_path'] for r in reviews})!=len(reviews): p.error('Duplicate review rows')
    if {r['relative_path'] for r in reviews}!=set(indexed): p.error('Review must account for every inventory record')
    included=[]; counts={}; failures=[]
    for row in reviews:
        decision=row['decision'].strip().lower(); counts[decision]=counts.get(decision,0)+1
        if decision not in {'include','exclude','duplicate','non-source','uncertain','pending'}: p.error('Unknown review decision')
        original=indexed[row['relative_path']]
        if row['sha256']!=original['sha256']: p.error('Review hash does not match inventory')
        if decision in {'include','exclude','duplicate','non-source'} and not row['reason'].strip(): p.error('Decision requires a reason')
        if decision=='include':
            if original['extraction_status']!='ok': p.error('Included source requires successful extraction')
            if not row['read_scope'].strip() or not row['evidence_location'].strip(): p.error('Include requires read scope and evidence location')
            path=(source/row['relative_path']).resolve()
            if not path.is_relative_to(source) or file_hash(path)!=row['sha256']: p.error('Included source changed or escaped source folder')
            included.append((row,path))
    # Version the destination rather than mixing this review with an old selection.
    if selected.exists() and any(selected.iterdir()): p.error('Selected directory must be new or empty')
    selected.mkdir(parents=True,exist_ok=True)
    manifest=[]; by_hash={}
    for row,path in included:
        try:
            if row['sha256'] in by_hash: target=by_hash[row['sha256']]
            else:
                target,_=copy_verified(path,row['sha256'],selected); by_hash[row['sha256']]=target
            manifest.append(dict(source_path=row['relative_path'],target_path=str(target),sha256=row['sha256'],status='verified',reason=row['reason'],read_scope=row['read_scope']))
        except Exception as exc: failures.append(dict(source=row['relative_path'],error=str(exc)))
    write_csv(selected/'selection_manifest.csv',['source_path','target_path','sha256','status','reason','read_scope'],manifest)
    result=dict(status='partial' if failures or counts.get('pending',0) or counts.get('uncertain',0) else 'complete',decisions=counts,selected_unique=len(by_hash),failures=failures)
    atomic_json(selected/'selection_summary.json',result); print(json.dumps(result,indent=2))

if __name__=='__main__': main()
