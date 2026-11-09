"""Verify actual packaged build compiler/plugin and the supported runtime pairing."""
import argparse,hashlib,json,os,platform,subprocess
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();repo=Path(__file__).resolve().parents[1]
    if a.out.exists():raise ValueError('Receipt exists')
    lock=json.loads(Path(__file__).with_name('toolchain.lock.json').read_text());assets=json.loads((repo/'src/Contract.V1/obj/project.assets.json').read_text())
    package=next(Path(root)/'grpc.tools'/lock['grpcTools'] for root in assets['packageFolders'] if (Path(root)/'grpc.tools'/lock['grpcTools']).is_dir())
    if assets['libraries']['Grpc.Tools/'+lock['grpcTools']]['sha512']!=lock['nugetContentHash'] or hashlib.sha512(next(package.glob('*.nupkg')).read_bytes()).hexdigest()!=lock['rawSignedNupkgSha512']:raise ValueError('Compiler package identity changed')
    rid='win-x64' if os.name=='nt' else 'linux-x64';files=lock['nativeTools'][rid]
    for entry in files:
        if hashlib.sha256((package/entry['path']).read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Native generation tool changed')
    result=subprocess.run([str(package/files[0]['path']),'--version'],capture_output=True,text=True,check=True,timeout=15)
    if result.stdout.strip()!=lock['protocVersion']:raise ValueError('Compiler runtime mismatch')
    a.out.parent.mkdir(parents=True,exist_ok=True);receipt={'status':'PASS','host':platform.system(),'grpcTools':lock['grpcTools'],'actualProtoc':result.stdout.strip(),'googleProtobuf':lock['googleProtobufRuntime'],'nativeToolHashes':files,'boundary':lock['compatibility']};a.out.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':main()
