"""Exact clean source -> four immutable self-contained apps -> local/native archive.
Adapted from public MIT Fenced Shard Ownership Lab delivery controls.
Never creates repositories, pushes, tags, publishes, overwrites or installs.
"""
import argparse,base64,datetime,hashlib,json,os,platform,shutil,subprocess,tarfile,uuid,xml.etree.ElementTree as ET,zipfile
from pathlib import Path
import notices

ROOT=Path(__file__).resolve().parents[1]
def require(condition,message):
    if not condition:raise ValueError(message)
def sha(file,algorithm='sha256'):
    result=hashlib.new(algorithm)
    with file.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()
def git(*args):return subprocess.check_output(['git','-C',str(ROOT),*args],text=True).strip()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for field in ['commit','rid','work','out','buf']:p.add_argument('--'+field,required=True)
    p.add_argument('--dotnet',default='dotnet');p.add_argument('--local-candidate',action='store_true');a=p.parse_args()
    require(a.rid in ['win-x64','linux-x64'] and git('rev-parse','HEAD')==a.commit and not git('status','--porcelain'),'Exact clean HEAD required')
    if not a.local_candidate:require(platform.system()==('Windows' if a.rid=='win-x64' else 'Linux'),'Native public build host must match RID')
    work=Path(a.work).resolve();work.mkdir(parents=True,exist_ok=False);out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
    version=ET.parse(ROOT/'Directory.Build.props').findtext('.//Version');name='contract-evolution-lab-v'+version+'-'+a.rid;package=work/name;package.mkdir()
    with (work/'locked-restore.log').open('wb') as log:subprocess.run([a.dotnet,'restore','ContractEvolution.slnx','--locked-mode'],cwd=ROOT,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=240)
    subprocess.run(['python' if os.name=='nt' else 'python3',str(ROOT/'tools/build_apps.py'),'--dotnet',a.dotnet,'--rid',a.rid,'--commit',a.commit,'--out',str(package/'apps')],check=True,cwd=ROOT,timeout=900,capture_output=True)
    for log in (package/'apps').glob('*-build.log'):shutil.copy2(log,work/log.name);log.unlink()
    subprocess.run(['python' if os.name=='nt' else 'python3',str(ROOT/'tools/check_contracts.py'),'--buf',a.buf,'--out',str(work/'contract-checks')],check=True,cwd=ROOT,capture_output=True,timeout=180)
    (package/'descriptors').mkdir()
    for ver in ['v1','v2']:shutil.copy2(work/'contract-checks'/(ver+'.bin'),package/'descriptors'/(ver+'.bin'))
    for file in ['README.md','LICENSE','NOTICE.md','PROVENANCE.md','SIGNING-PUBLIC-KEY.pub','CONTRIBUTING.md']:shutil.copy2(ROOT/file,package/file)
    for directory in ['docs','tools','vendor','contracts']:shutil.copytree(ROOT/directory,package/directory,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    # Test verifier uses only the tiny public signed fixture, never a signing private key.
    shutil.copytree(ROOT/'tests/provenance-fixture',package/'tests/provenance-fixture')
    graph={};folders=set();regular={}
    for version_number in [1,2]:
        for role in ['Producer','Consumer']:
            app=role.lower()+'-v'+str(version_number);project=ROOT/f'src/{role}.V{version_number}'
            assets=json.loads((project/'obj/project.assets.json').read_text());folders.update(assets['packageFolders']);libraries=assets['libraries']
            locks=json.loads((project/'packages.lock.json').read_text())['dependencies']
            locked={(key,value['resolved'],value['contentHash']) for scope in locks.values() for key,value in scope.items() if 'contentHash' in value}
            deps=json.loads((package/'apps'/app/(app+'.deps.json')).read_text())
            require(a.commit.encode() in (package/'apps'/app/(app+'.dll')).read_bytes(),'Source metadata absent')
            for identity,entry in deps['libraries'].items():
                if entry['type'] not in ['package','runtimepack']:continue
                identity=identity.removeprefix('runtimepack.');key,ver=identity.split('/')
                record=graph.setdefault(identity,{'apps':[],'kind':entry['type']});record['apps'].append(app)
                if entry['type']=='package':
                    asset=libraries[identity];require((key,ver,asset['sha512']) in locked,'Shipped package differs from lock');regular[identity]=asset
    mappings=json.loads((ROOT/'vendor/notices/NOTICE-SOURCES.json').read_text())['components'];dependencies=[];licenses=package/'licenses';licenses.mkdir()
    for identity,record in sorted(graph.items()):
        identifier,ver=identity.split('/');directory=next(Path(f)/identifier.lower()/ver for f in folders if (Path(f)/identifier.lower()/ver).is_dir())
        metadata=ET.parse(next(directory.glob('*.nuspec'))).find('{*}metadata')
        content_hash=json.loads((directory/'.nupkg.metadata').read_text())['contentHash'];entry=regular.get(identity,{'sha512':content_hash})
        require(entry['sha512']==content_hash,'Restore metadata and locked content identity differ')
        mapped=next(m for m in mappings if m['id']+'/'+m['version']==identity)
        # The contentHash excludes signatures; actual archive SHA512 is a separate value.
        archive=next(directory.glob('*.nupkg'));raw_sha512=sha(archive,'sha512')
        require(base64.b64decode(mapped['rawSignedNupkgSha512Base64']).hex()==raw_sha512,'Raw signed NuGet archive changed')
        notice=notices.resolve(ROOT,directory,identity,entry,metadata);prefix=identifier+'-'+ver
        for file in notice['suppliedNotices']:shutil.copy2(file,licenses/(prefix+'-'+file.name))
        primary=licenses/(prefix+'-PRIMARY-LICENSE.txt');shutil.copy2(notice['primary'],primary)
        copyright_file=licenses/(prefix+'-COPYRIGHT.txt');copyright_file.write_text(notice['copyright']+'\n',encoding='utf-8',newline='\n')
        dependencies.append({'id':identifier,'version':ver,'kind':record['kind'],'usedBy':record['apps'],'license':notice['license'],'copyright':notice['copyright'],'nugetContentHash':content_hash,'nugetContentHashMeaning':'NuGet normalized package content excluding signatures','rawSignedNupkgSha512':raw_sha512,'licenseFile':primary.relative_to(package).as_posix(),'licenseSha256':sha(primary),'copyrightFile':copyright_file.relative_to(package).as_posix(),'licenseSource':notice['licenseSource']})
    require(len(dependencies)==10,'Unexpected reviewed shipped graph')
    (package/'DEPENDENCIES.json').write_text(json.dumps({'packages':dependencies,'excludedBuildTools':['Grpc.Tools/2.85.0','xunit.v3/4.0.3'],'externalReferences':['tools/upstream.lock.json (five PostgreSQL/support archives)','tools/buf.lock.json (Buf, separately fetched)']},indent=2)+'\n')
    app_spdx={'name':'Contract Evolution & Safe Rollout Lab','SPDXID':'SPDXRef-App','versionInfo':version,'downloadLocation':'NOASSERTION','filesAnalyzed':False,'licenseDeclared':'MIT','copyrightText':'Copyright (c) 2026 Pouria Jamali'}
    packages=[app_spdx];relationships=[{'spdxElementId':'SPDXRef-DOCUMENT','relationshipType':'DESCRIBES','relatedSpdxElement':'SPDXRef-App'}]
    for i,dep in enumerate(dependencies):
        spdxid='SPDXRef-Package'+str(i);key=dep['id'].lower();ver=dep['version']
        packages.append({'name':dep['id'],'SPDXID':spdxid,'versionInfo':ver,'downloadLocation':f'https://api.nuget.org/v3-flatcontainer/{key}/{ver}/{key}.{ver}.nupkg','filesAnalyzed':False,'licenseDeclared':dep['license'],'licenseConcluded':'NOASSERTION','copyrightText':dep['copyright'],'checksums':[{'algorithm':'SHA512','checksumValue':dep['rawSignedNupkgSha512']}],'comment':'Raw signed archive checksum at build; normalized NuGet restore identity is in DEPENDENCIES.json.'})
        relationships.append({'spdxElementId':'SPDXRef-App','relationshipType':'DEPENDS_ON','relatedSpdxElement':spdxid})
    sbom={'spdxVersion':'SPDX-2.3','dataLicense':'CC0-1.0','SPDXID':'SPDXRef-DOCUMENT','name':name,'documentNamespace':'https://github.com/pouriajamali/contract-evolution-lab/spdx/'+str(uuid.uuid4()),'creationInfo':{'creators':['Tool: contract-evolution-package.py'],'created':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},'packages':packages,'relationships':relationships}
    (package/'SBOM.spdx.json').write_text(json.dumps(sbom,indent=2)+'\n')
    require(not git('status','--porcelain'),'Build changed frozen source/lockfiles')
    files=[]
    for file in sorted(package.rglob('*')):
        require(not file.is_symlink(),'No package symlinks')
        if not file.is_file():continue
        relative=file.relative_to(package).as_posix();require(not relative.lower().endswith(('.pdb','.private.json','.db','.sqlite')),'Private/debug/data file in package')
        files.append({'path':relative,'bytes':file.stat().st_size,'sha256':sha(file)})
    require(len(files)<=4096 and sum(f['bytes'] for f in files)<=768*1024*1024,'Package cap exceeded')
    manifest={'schema':1,'version':version,'rid':a.rid,'sourceCommit':a.commit,'sourceTree':git('rev-parse','HEAD^{tree}'),'localCandidate':a.local_candidate,'buildHost':platform.system(),'selfContained':True,'files':files}
    (package/'BUILD-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    archive=out/(name+('.zip' if a.rid=='win-x64' else '.tar.gz'));require(not archive.exists(),'Archive exists')
    if a.rid=='win-x64':
        with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as zipped:
            for file in sorted(package.rglob('*')):
                if file.is_file():zipped.write(file,file.relative_to(work).as_posix())
    else:
        with tarfile.open(archive,'x:gz') as packed:
            for file in sorted(package.rglob('*')):
                if not file.is_file():continue
                info=packed.gettarinfo(str(file),arcname=file.relative_to(work).as_posix());info.mode=0o755 if file.name in ['producer-v1','producer-v2','consumer-v1','consumer-v2','createdump'] else 0o644;info.uid=info.gid=0;info.uname=info.gname=''
                with file.open('rb') as stream:packed.addfile(info,stream)
    receipt={'status':'PACKAGED_NOT_RUNTIME_PROOF','sourceCommit':a.commit,'rid':a.rid,'localCandidate':a.local_candidate,'archive':str(archive),'bytes':archive.stat().st_size,'sha256':sha(archive),'payloadFiles':len(files),'shippedComponents':len(dependencies)}
    (work/'archive.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))

if __name__=='__main__':main()
