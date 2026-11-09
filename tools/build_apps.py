"""Build four separate self-contained immutable native app directories."""
import argparse,hashlib,json,os,platform,subprocess
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dotnet',required=True);p.add_argument('--rid',choices=['win-x64','linux-x64'],required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--commit',default='LOCAL_UNCOMMITTED');a=p.parse_args()
    repo=Path(__file__).resolve().parents[1];a.out.mkdir(parents=True,exist_ok=False);records=[]
    for version in [1,2]:
        for role in ['Producer','Consumer']:
            project=repo/f'src/{role}.V{version}/{role}.V{version}.csproj';out=a.out/f'{role.lower()}-v{version}'
            result=subprocess.run([a.dotnet,'publish',str(project),'-c','Release','-r',a.rid,'--self-contained','true','--no-restore','--nologo','-m:1','-p:UseSharedCompilation=false','-p:SourceRevisionId='+a.commit,'-o',str(out)],cwd=repo,capture_output=True,text=True,timeout=240)
            (a.out/f'{role.lower()}-v{version}-build.log').write_text(result.stdout+result.stderr)
            if result.returncode:raise ValueError('Native app build failed; inspect '+role+str(version)+' build log')
            app=out/(f'{role.lower()}-v{version}'+('.exe' if a.rid=='win-x64' else ''))
            records.append({'role':role.lower(),'version':version,'apphostSha256':hashlib.sha256(app.read_bytes()).hexdigest(),'managedSha256':hashlib.sha256((out/f'{role.lower()}-v{version}.dll').read_bytes()).hexdigest()})
    receipt={'status':'BUILT_NOT_RUNTIME_PROOF','rid':a.rid,'buildHost':platform.system(),'sourceCommit':a.commit,'apps':records}
    (a.out/'APPS.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':main()
