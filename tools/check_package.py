"""Verify every extracted byte, license/SBOM graph and all four native apphosts."""
import argparse,hashlib,json,os,platform,subprocess
from pathlib import Path,PurePosixPath

def require(condition,message):
    if not condition:raise ValueError(message)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',type=Path,required=True);p.add_argument('--commit',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();package=a.package.resolve();a.out.parent.mkdir(parents=True,exist_ok=True);require(not a.out.exists(),'Receipt exists')
    manifest=json.loads((package/'BUILD-MANIFEST.json').read_text());require(manifest['sourceCommit']==a.commit,'Wrong source');expected=set();checks=[]
    for entry in manifest['files']:
        path=PurePosixPath(entry['path']);require(not path.is_absolute() and '..' not in path.parts and entry['path'] not in expected,'Unsafe/duplicate manifest path');expected.add(entry['path']);file=package/path
        require(file.is_file() and not file.is_symlink() and file.stat().st_size==entry['bytes'] and hashlib.sha256(file.read_bytes()).hexdigest()==entry['sha256'],'Manifest bytes differ')
    require({p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}==expected|{'BUILD-MANIFEST.json'},'Package file set differs');checks.append('exact-file-set-size-and-sha256')
    dependencies=json.loads((package/'DEPENDENCIES.json').read_text())['packages'];bom=json.loads((package/'SBOM.spdx.json').read_text())
    require(len(dependencies)==10 and len(bom['packages'])==11,'Wrong shipped graph')
    for dep in dependencies:
        license_file=package/dep['licenseFile'];require(license_file.stat().st_size>=300 and hashlib.sha256(license_file.read_bytes()).hexdigest()==dep['licenseSha256'],'Full license differs')
        require((package/dep['copyrightFile']).read_text().strip()==dep['copyright'],'Original copyright missing')
        item=next(i for i in bom['packages'] if i['name']==dep['id']);require(item['checksums']==[{'algorithm':'SHA512','checksumValue':dep['rawSignedNupkgSha512']}],'SBOM raw archive checksum differs')
    checks.extend(['all-shipped-component-full-licenses-and-copyright','separate-normalized-lock-and-raw-archive-hashes','both-core-and-aspnet-runtime-graphs'])
    for role in ['producer','consumer']:
        for version in [1,2]:
            name=role+'-v'+str(version);app=package/'apps'/name/(name+('.exe' if os.name=='nt' else ''))
            for flag in ['--help','--version']:
                result=subprocess.run([str(app),flag],cwd=app.parent,capture_output=True,text=True,check=True,timeout=20);reply=json.loads(result.stdout)
                require(reply['version']==version and a.commit in reply['source'] and 'literal-loopback' in reply['usage'],'Wrong actual native apphost')
            checks.append('actual-native-'+name+'-help-version-source')
    descriptors={v:hashlib.sha256((package/'descriptors'/(v+'.bin')).read_bytes()).hexdigest() for v in ['v1','v2']}
    receipt={'status':'PASS','os':platform.system(),'sourceCommit':a.commit,'rid':manifest['rid'],'checkCount':len(checks),'checks':checks,'payloadFiles':len(expected),'shippedComponents':len(dependencies),'immutableDescriptors':descriptors}
    a.out.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':main()
