"""Real local Buf lint/FILE checks, immutable descriptors and a rejected wire break."""
import argparse,hashlib,json,shutil,subprocess
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--buf',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False);repo=Path(__file__).resolve().parents[1];buf=a.buf.resolve();out=a.out.resolve()
    def call(args,expected=0):
        result=subprocess.run([str(buf),*map(str,args)],cwd=repo,capture_output=True,text=True,timeout=45)
        (out/('command-'+str(len(list(out.glob('command-*.json'))))+'.json')).write_text(json.dumps({'args':list(map(str,args)),'exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr},indent=2)+'\n')
        if (expected==0 and result.returncode!=0) or (expected!=0 and result.returncode==0):raise ValueError('Buf expected result mismatch')
        return result.stdout.strip()
    if call(['--version'])!='1.75.0':raise ValueError('Wrong Buf version')
    for version in ['v1','v2']:
        call(['lint','contracts/'+version])
        call(['build','contracts/'+version,'--as-file-descriptor-set','-o',out/(version+'.bin')])
    call(['breaking','contracts/v2','--against',out/'v1.bin'])
    broken=out/'broken';shutil.copytree(repo/'contracts/v2',broken)
    proto=broken/'evolution/v1/actions.proto';original=proto.read_text()
    if original.count('int64 amount = 5;')!=1:raise ValueError('Negative fixture drift')
    proto.write_text(original.replace('int64 amount = 5;','string amount = 5;'))
    call(['breaking',broken,'--against',out/'v1.bin'],expected=1)
    receipt={'status':'PASS','bufVersion':'1.75.0','policy':'FILE','checks':['v1-standard-lint','v2-standard-lint','additive-FILE-compatible','type-change-rejected'],'descriptors':{v:hashlib.sha256((out/(v+'.bin')).read_bytes()).hexdigest() for v in ['v1','v2']}}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':main()
