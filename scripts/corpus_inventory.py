#!/usr/bin/env python3
"""Inventory with durable checkpoints and verified copies; candidates require review."""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import unicodedata
import zipfile
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree as ET

VERSION = 2
SUPPORTED = {'.pdf', '.docx', '.txt', '.doc', '.rtf'}
DOI_RE = re.compile(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', re.I)
FIELDS = ['record_id','relative_path','extension','size_bytes','sha256','title','title_source','author','year','doi','extraction_status','read_scope','text_path','cache_reused']

def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): digest.update(block)
    return digest.hexdigest()

def normalize(value):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', value).casefold()))

def clean_doi(value):
    value = value.rstrip('.,;:')
    for opening, closing in [('(',')'),('[',']'),('{','}')]:
        while value.endswith(closing) and value.count(closing)>value.count(opening): value=value[:-1]
    return value.lower()

def atomic_json(path, value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary,path)

def write_csv(path, fields, rows):
    temporary=path.with_suffix('.csv.tmp')
    with temporary.open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)
    os.replace(temporary,path)

def labelled(text, labels):
    match=re.search(r'(?im)^\s*(?:'+labels+r')\s*:\s*([^\n\r]+)',text)
    return match.group(1).strip() if match else ''

def extract(path, full_text=False):
    result=dict(title='',title_source='',author='',year='',doi='',extraction_status='ok',read_scope='',text='')
    try:
        if path.suffix.lower()=='.pdf':
            from pypdf import PdfReader
            reader=PdfReader(str(path))
            if reader.is_encrypted:
                result['extraction_status']='encrypted'; return result
            metadata=reader.metadata or {}
            result['title']=str(metadata.get('/Title') or '').strip()
            result['author']=str(metadata.get('/Author') or '').strip()
            count=len(reader.pages) if full_text else min(3,len(reader.pages))
            pages=[page.extract_text() or '' for page in reader.pages[:count]]
            result['text']='\n'.join(f'[[PDF page {i+1}]]\n{t}' for i,t in enumerate(pages))
            result['read_scope']=f'extracted {count}/{len(reader.pages)} pages; visual verification pending'
            if any(not t.strip() for t in pages) or not pages: result['extraction_status']='needs-ocr-or-empty-page'
        elif path.suffix.lower()=='.docx':
            with zipfile.ZipFile(path) as archive:
                if 'docProps/core.xml' in archive.namelist():
                    for node in ET.fromstring(archive.read('docProps/core.xml')).iter():
                        if node.tag.endswith('}title'): result['title']=node.text or ''
                        elif node.tag.endswith('}creator'): result['author']=node.text or ''
                parts=[]
                for name in archive.namelist():
                    if re.fullmatch(r'word/(document|footnotes|endnotes|comments|header\d*|footer\d*)\.xml',name):
                        root=ET.fromstring(archive.read(name))
                        paragraphs=[''.join(n.text or '' for n in p.iter() if n.tag.endswith('}t')) for p in root.iter() if p.tag.endswith('}p')]
                        parts.append(f'[[{name}]]\n'+'\n'.join(paragraphs))
                result['text']='\n'.join(parts)
                result['read_scope']='DOCX text parts; drawings/equations/layout require visual verification'
        elif path.suffix.lower()=='.txt':
            result['text']=path.read_text(encoding='utf-8-sig'); result['read_scope']='entire UTF-8 text'
        else:
            result['extraction_status']='conversion-required'; return result
        # Use explicit bibliographic labels before references, never first DOI/year.
        text=result['text']
        head=re.split(r'(?im)^\s*(?:references|bibliography|daftar pustaka)\s*:?',text,1)[0][:20000]
        title=labelled(head,'title|judul')
        result['title_source']='document-metadata' if result['title'] else ''
        if title: result['title']=title; result['title_source']='label'
        result['author']=labelled(head,'authors?|penulis') or result['author']
        publication=labelled(head,'publication year|published|year|tahun|tahun terbit')
        year=re.search(r'\b(?:19|20)\d{2}\b',publication)
        result['year']=year.group() if year else ''
        doi=DOI_RE.search(labelled(head,'doi'))
        result['doi']=clean_doi(doi.group()) if doi else ''
        if not re.sub(r'\[\[.*?\]\]','',text).strip(): result['extraction_status']='empty-text'
    except Exception as exc:
        result['extraction_status']='extraction-error:'+type(exc).__name__
    return result

def choose_target(source, digest, destination):
    choices=[destination/source.name,destination/f'{source.stem}__{digest[:12]}{source.suffix}']
    index=2
    while True:
        target=choices.pop(0) if choices else destination/f'{source.stem}__{digest[:12]}_{index}{source.suffix}'
        if not target.exists(): return target,False
        if target.is_file() and file_hash(target)==digest: return target,True
        index+=1

def copy_verified(source,digest,destination):
    if file_hash(source)!=digest: raise ValueError('source-changed-after-inventory')
    target,existing=choose_target(source,digest,destination)
    if not existing:
        with source.open('rb') as src, target.open('xb') as dst:
            for block in iter(lambda: src.read(1024*1024),b''): dst.write(block)
        if file_hash(target)!=digest: raise ValueError('copy-hash-mismatch:'+str(target))
    return target,existing

def candidates(records):
    groups=[]; dois=defaultdict(list)
    for row in records:
        if row['doi']: dois[row['doi']].append(row)
    for doi,members in sorted(dois.items()):
        if len({r['sha256'] for r in members})>1: groups.append(('doi',doi,members))
    blocks=defaultdict(list)
    for row in records:
        if row['title_source'] and row['author'] and row['year']:
            blocks[(normalize(row['author']),row['year'])].append(row)
    seen=set()
    for members in blocks.values():
        for i,left in enumerate(members):
            for right in members[i+1:]:
                key=tuple(sorted([left['sha256'],right['sha256']]))
                if key[0]==key[1] or key in seen: continue
                if left['doi'] and right['doi']: continue
                a,b=normalize(left['title']),normalize(right['title'])
                similarity=SequenceMatcher(None,a,b).ratio()
                if min(len(a),len(b))>=16 and similarity>=0.92:
                    seen.add(key); groups.append(('title-author-year',str(round(similarity,3)),[left,right]))
    rows=[]
    for index,(basis,key,members) in enumerate(groups,1):
        for m in members:
            rows.append(dict(candidate_group_id=f'biblio-{index:05}',basis=basis,key=key,member_path=m['relative_path'],sha256=m['sha256'],title=m['title'],author=m['author'],year=m['year'],doi=m['doi'],decision='review-required'))
    return groups,rows

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--copy-exact-unique-to',type=Path)
    parser.add_argument('--full-text',action='store_true',help='Extract all PDF pages; not visual QA')
    parser.add_argument('--refresh',action='store_true',help='Re-extract successful cached records')
    args=parser.parse_args()
    source=args.source.resolve(); reports=args.report_dir.resolve()
    dest=args.copy_exact_unique_to.resolve() if args.copy_exact_unique_to else None
    if not source.is_dir(): parser.error('Source must be a readable folder')
    for target in [reports,dest]:
        if target and (target==source or source in target.parents or target in source.parents): parser.error('Outputs cannot overlap source')
    if dest and (dest==reports or dest in reports.parents or reports in dest.parents): parser.error('Copy and report folders must be separate')
    reports.mkdir(parents=True,exist_ok=True)
    cache_dir=reports/'checkpoints'; cache_dir.mkdir(exist_ok=True)
    text_dir=reports/'texts'; text_dir.mkdir(exist_ok=True)
    if dest: dest.mkdir(parents=True,exist_ok=True)
    records=[]; unsupported=[]; hashes=defaultdict(list); reused=0
    atomic_json(reports/'summary.json',{'status':'running','source':str(source),'version':VERSION})
    for path in sorted(source.rglob('*')):
        if path.is_dir(): continue
        relative=str(path.relative_to(source))
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            unsupported.append(dict(relative_path=relative,reason='external-or-symbolic-link')); continue
        if path.suffix.lower() not in SUPPORTED:
            unsupported.append(dict(relative_path=relative,reason='unsupported-extension')); continue
        row=dict.fromkeys(FIELDS,''); row.update(record_id=len(records)+1,relative_path=relative,extension=path.suffix.lower())
        try:
            stat=path.stat(); digest=file_hash(path)
            row.update(size_bytes=stat.st_size,sha256=digest)
            cache_key=f'{digest}-{path.suffix.lower()[1:]}-{int(args.full_text)}-v{VERSION}'
            cache_file=cache_dir/(cache_key+'.json'); cached=None
            if cache_file.exists() and not args.refresh:
                try: cached=json.loads(cache_file.read_text(encoding='utf-8'))
                except (ValueError,OSError): pass
            if cached and cached.get('extraction_status')=='ok' and cached.get('version')==VERSION and (text_dir/(cache_key+'.txt')).exists():
                data=cached; reused+=1; row['cache_reused']=True
            else:
                data=extract(path,args.full_text)
                if file_hash(path)!=digest: raise ValueError('source-changed-during-extraction')
                text_file=text_dir/(cache_key+'.txt'); temporary=text_file.with_suffix('.tmp')
                temporary.write_text(data.pop('text',''),encoding='utf-8'); os.replace(temporary,text_file)
                data.update(version=VERSION,text_path=str(text_file)); atomic_json(cache_file,data)
                row['cache_reused']=False
            row.update({k:v for k,v in data.items() if k in FIELDS})
            if not row['title']: row['title']=path.stem
            hashes[digest].append(row)
        except Exception as exc: row['extraction_status']='inventory-error:'+str(exc)
        records.append(row)
    write_csv(reports/'inventory.csv',FIELDS,records)
    write_csv(reports/'unsupported.csv',['relative_path','reason'],unsupported)
    exact=[]
    for digest,members in hashes.items():
        if len(members)>1: exact.extend(dict(group_id=digest,sha256=digest,canonical_path=members[0]['relative_path'],member_path=m['relative_path']) for m in members)
    write_csv(reports/'exact_duplicates.csv',['group_id','sha256','canonical_path','member_path'],exact)
    groups,rows=candidates([r for r in records if r['extraction_status']=='ok'])
    write_csv(reports/'duplicate_candidates.csv',['candidate_group_id','basis','key','member_path','sha256','title','author','year','doi','decision'],rows)
    copied=skipped=0; manifest=[]
    if dest:
        for digest,members in hashes.items():
            good=[r for r in members if r['extraction_status']=='ok']
            if not good:
                manifest.extend(dict(source_path=m['relative_path'],target_path='',sha256=digest,status='held-unreadable') for m in members); continue
            try:
                target,existing=copy_verified(source/good[0]['relative_path'],digest,dest)
                copied+=not existing; skipped+=existing
                manifest.extend(dict(source_path=m['relative_path'],target_path=str(target),sha256=digest,status='verified-existing' if existing else 'verified-copy') for m in members)
            except Exception as exc: manifest.extend(dict(source_path=m['relative_path'],target_path='',sha256=digest,status='copy-error:'+str(exc)) for m in members)
    write_csv(reports/'copy_manifest.csv',['source_path','target_path','sha256','status'],manifest)
    failures=sum(r['extraction_status']!='ok' for r in records)
    copy_failures=sum(m['status'].startswith('copy-error:') for m in manifest)
    summary=dict(status='complete-with-issues' if failures or copy_failures else 'complete',version=VERSION,source=str(source),supported_files=len(records),unsupported_files=len(unsupported),total_files=len(records)+len(unsupported),inventory_failures=failures,metadata_reused_by_hash=reused,unique_sha256=len(hashes),exact_duplicate_groups=sum(len(v)>1 for v in hashes.values()),exact_duplicate_extra_copies=sum(len(v)-1 for v in hashes.values()),bibliographic_candidate_groups=len(groups),copied_exact_unique=copied,copy_skipped_existing_same_hash=skipped,copy_failure_records=copy_failures,note='Candidates require review. Exact-unique copies are not relevance-screened. Extracted text is not visual verification.')
    atomic_json(reports/'summary.json',summary); print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__': sys.exit(main())
