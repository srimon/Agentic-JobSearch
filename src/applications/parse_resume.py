"""Bounded subprocess parser. Never render files or follow embedded links."""
import io
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

MAX_BYTES=5*1024*1024
MAX_TEXT=120000

def extract(raw,extension):
    if not raw or len(raw)>MAX_BYTES: raise ValueError('File size rejected')
    if extension=='txt':
        text=raw.decode('utf-8-sig')
        if '\x00' in text: raise ValueError('Binary content rejected')
    elif extension=='pdf':
        from pypdf import PdfReader
        if not raw.startswith(b'%PDF-'): raise ValueError('Invalid PDF')
        reader=PdfReader(io.BytesIO(raw),strict=True)
        if reader.is_encrypted or len(reader.pages)>30: raise ValueError('Protected or long PDF')
        # Active content is not executed; reject its containers as an additional precaution.
        root=reader.trailer['/Root']
        if '/OpenAction' in root or '/AA' in root or '/AcroForm' in root: raise ValueError('Active PDF')
        names=root.get('/Names',{})
        if hasattr(names,'get_object'): names=names.get_object()
        if '/JavaScript' in names or '/EmbeddedFiles' in names: raise ValueError('Active PDF')
        parts=[]
        for page in reader.pages:
            parts.append(page.extract_text() or '')
            if sum(map(len,parts))>MAX_TEXT: raise ValueError('Text too large')
        text='\n'.join(parts)
    elif extension=='docx':
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            entries=z.infolist()
            if len(entries)>200 or sum(x.file_size for x in entries)>15*1024*1024: raise ValueError('Archive too large')
            if any('vbaproject' in x.filename.lower() or '/embeddings/' in x.filename.lower() for x in entries): raise ValueError('Active document')
            if 'word/document.xml' not in z.namelist(): raise ValueError('Not DOCX')
            data=z.read('word/document.xml')
            if b'<!DOCTYPE' in data or b'<!ENTITY' in data: raise ValueError('XML declarations rejected')
            root=ET.fromstring(data)
            ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            text='\n'.join(' '.join(t.text or '' for t in para.iter(ns+'t')) for para in root.iter(ns+'p'))
    else: raise ValueError('Unsupported file')
    text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',text).strip()
    if len(text)<80 or len(text)>MAX_TEXT: raise ValueError('Insufficient or excessive readable text')
    return text

if __name__=='__main__':
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(320*1024*1024,320*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(8,8))
    try:
        print(extract(sys.stdin.buffer.read(MAX_BYTES+1),sys.argv[1]),end='')
    except Exception:
        sys.exit(2)
