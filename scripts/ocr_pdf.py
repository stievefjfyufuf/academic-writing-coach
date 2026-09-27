#!/usr/bin/env python3
"""Render a scanned PDF and OCR each page with bundled Tesseract.js.

Language data may require network access on first use. OCR output is evidence for
manual verification, not a replacement for checking the rendered page.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()


def bundled_paths():
    dependencies=Path(sys.executable).resolve().parent.parent
    return {
        'node': dependencies/'node/bin/node.exe',
        'module': dependencies/'node/node_modules/tesseract.js',
        'pdftoppm': dependencies/'native/poppler/Library/bin/pdftoppm.exe',
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--lang',default='eng',help='Tesseract language, e.g. eng or ind+eng')
    parser.add_argument('--dpi',type=int,default=250)
    args=parser.parse_args()
    source=args.pdf.resolve(); output=args.output_dir.resolve()
    if not source.is_file() or source.suffix.lower()!='.pdf': parser.error('Input must be a PDF file')
    if source.parent==output or source.parent in output.parents: parser.error('OCR output must be outside the source folder')
    if not 100<=args.dpi<=600: parser.error('DPI must be between 100 and 600')
    paths=bundled_paths()
    missing=[name for name,path in paths.items() if not path.exists()]
    if missing: parser.error('Bundled dependency unavailable: '+', '.join(missing))
    output.mkdir(parents=True,exist_ok=True)
    images=output/'pages'; images.mkdir(exist_ok=True)
    prefix=images/'page'
    render=subprocess.run([str(paths['pdftoppm']),'-r',str(args.dpi),'-png',str(source),str(prefix)],capture_output=True,text=True)
    if render.returncode: raise RuntimeError(render.stderr or 'PDF rendering failed')
    pages=sorted(images.glob('page-*.png'))
    if not pages: raise RuntimeError('No pages rendered')
    worker=output/'ocr_worker.cjs'
    result_path=output/'ocr_pages.json'
    worker.write_text("""const fs=require('fs');
const {createWorker}=require(process.argv[2]);
(async()=>{const lang=process.argv[3],cache=process.argv[4],out=process.argv[5],pages=process.argv.slice(6);
const worker=await createWorker(lang,1,{cachePath:cache});const results=[];
for(let i=0;i<pages.length;i++){const r=await worker.recognize(pages[i]);results.push({page:i+1,image:pages[i],confidence:r.data.confidence,text:r.data.text});}
await worker.terminate();fs.writeFileSync(out,JSON.stringify(results,null,2),'utf8');})().catch(e=>{console.error(e);process.exit(1)});
""",encoding='utf-8')
    cache=output/'language-cache'; cache.mkdir(exist_ok=True)
    ocr=subprocess.run([str(paths['node']),str(worker),str(paths['module']),args.lang,str(cache),str(result_path),*[str(p) for p in pages]],capture_output=True,text=True)
    if ocr.returncode: raise RuntimeError(ocr.stderr or 'OCR failed')
    records=json.loads(result_path.read_text(encoding='utf-8'))
    text_path=output/'ocr_text.txt'
    text_path.write_text('\n\n'.join(f"[[OCR page {r['page']} | confidence {r['confidence']:.1f}]]\n{r['text'].strip()}" for r in records),encoding='utf-8')
    manifest={'source':str(source),'source_sha256':sha256(source),'language':args.lang,'dpi':args.dpi,'pages':len(records),'minimum_confidence':min(r['confidence'] for r in records),'text':str(text_path),'page_images':str(images),'requires_visual_verification':True}
    (output/'ocr_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
