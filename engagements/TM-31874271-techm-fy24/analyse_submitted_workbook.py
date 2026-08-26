import zipfile, re, sys, csv, os
from xml.etree.ElementTree import iterparse
NS="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
F="Tech Mahindra FY24 Audit Financials.xlsx"

def shared(z):
    out=[];buf=None
    if "xl/sharedStrings.xml" not in z.namelist(): return out
    for ev,el in iterparse(z.open("xl/sharedStrings.xml"),("start","end")):
        if el.tag==NS+"si":
            if ev=="start": buf=[]
            else: out.append("".join(buf)); el.clear()
        elif ev=="end" and el.tag==NS+"t" and buf is not None: buf.append(el.text or "")
    return out

def target(z,name):
    wbx=z.read("xl/workbook.xml").decode("utf8","ignore")
    rels=z.read("xl/_rels/workbook.xml.rels").decode("utf8","ignore")
    rid=re.search(r'<sheet[^>]*name="%s"[^>]*r:id="([^"]+)"'%re.escape(name),wbx).group(1)
    t=re.search(r'Id="%s"[^>]*Target="([^"]+)"'%re.escape(rid),rels).group(1)
    return "xl/"+t.lstrip("/").replace("../","")

def col(r):
    n=0
    for ch in r:
        if not ch.isalpha(): break
        n=n*26+(ord(ch.upper())-64)
    return n-1

def rows(name):
    z=zipfile.ZipFile(F); ss=shared(z)
    for ev,el in iterparse(z.open(target(z,name)),("end",)):
        if el.tag!=NS+"row": continue
        cells={}
        for c in el.findall(NS+"c"):
            v=c.find(NS+"v"); t=c.get("t")
            if t=="inlineStr":
                node=c.find(NS+"is")
                val="".join(x.text or "" for x in node.iter(NS+"t")) if node is not None else ""
            elif v is None: val=""
            elif t=="s": val=ss[int(v.text)]
            elif t=="e": val=v.text or "#ERR"
            else: val=v.text or ""
            cells[col(c.get("r","A1"))]=val
        yield [cells.get(i,"") for i in range(max(cells)+1)] if cells else []
        el.clear()

if __name__=="__main__":
    name=sys.argv[1]; out=sys.argv[2] if len(sys.argv)>2 else None
    n=0; errs=0
    w=csv.writer(open(out,"w",newline="")) if out else None
    for r in rows(name):
        n+=1; errs+=sum(1 for v in r if isinstance(v,str) and v.startswith("#"))
        if w: w.writerow(r)
        elif n<=5: print(r[:14])
    print(f"[{name}] rows={n:,} error-cells={errs:,}")
