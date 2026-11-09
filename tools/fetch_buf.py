"""Fetch only the exact official Buf CLI for this native OS into a new file."""
import argparse,hashlib,json,os,platform,urllib.request
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--rid',choices=['win-x64','linux-x64']);a=p.parse_args()
    rid=a.rid or ('win-x64' if os.name=='nt' else 'linux-x64')
    if platform.machine().lower() not in {'amd64','x86_64'}:raise ValueError('x64 only')
    lock=json.loads(Path(__file__).with_name('buf.lock.json').read_text());name='buf-Windows-x86_64.exe' if rid=='win-x64' else 'buf-Linux-x86_64'
    entry=next(x for x in lock['assets'] if x['name']==name);a.out.mkdir(parents=True,exist_ok=False);target=a.out/name
    h=hashlib.sha256();size=0
    with urllib.request.urlopen(urllib.request.Request(entry['url'],headers={'User-Agent':'contract-evolution-bounded-fixture'}),timeout=90) as response,target.open('xb') as output:
        while chunk:=response.read(1024*1024):
            size+=len(chunk)
            if size>entry['bytes']:raise ValueError('Upstream size cap')
            output.write(chunk);h.update(chunk)
    if h.hexdigest()!=entry['sha256'] or size!=entry['bytes']:raise ValueError('Pinned upstream mismatch')
    if os.name!='nt':target.chmod(0o755)
    (a.out/'DOWNLOAD.json').write_text(json.dumps({'status':'PASS',**entry},indent=2)+'\n')
    print(json.dumps({'status':'PASS','tool':str(target),'version':lock['version']}))
if __name__=='__main__':main()
