"""Execute actual v1/v2 apphosts, gRPC matrix and one owned PG migration.
Native Windows uses an EXISTING Ubuntu-24.04 WSL instance for PostgreSQL only.
Output contains a private ephemeral connection file: never commit/upload it.
"""
import argparse,concurrent.futures,hashlib,json,os,platform,socket,subprocess,time
from pathlib import Path

def linux(path):
    path=Path(path).resolve()
    return '/mnt/'+path.drive[0].lower()+'/'+path.as_posix()[3:] if os.name=='nt' else str(path)

def atomic(path,value):
    temp=path.with_suffix('.partial');temp.write_text(json.dumps(value));os.replace(temp,path)

def require(condition,message):
    if not condition:raise ValueError(message)

# Reviewed literal wire bytes and outcomes, independent of Policy.Validate.
# Every frame has amount=2000, confirmed=true and one 9-byte synthetic identity.
SEMANTIC_CASES = (
    ("tuple-111", (1, 1, 1), "0a097475706c652d31313110011801200128d00f3801", ("APPLIED", "REPLAY"), 2000),
    ("tuple-112", (1, 1, 2), "0a097475706c652d31313210011801200228d00f3801", ("DENIED", "DENIED"), None),
    ("tuple-121", (1, 2, 1), "0a097475706c652d31323110011802200128d00f3801", ("DENIED", "DENIED"), None),
    ("tuple-122", (1, 2, 2), "0a097475706c652d31323210011802200228d00f3801", ("DENIED", "DENIED"), None),
    ("tuple-211", (2, 1, 1), "0a097475706c652d32313110021801200128d00f3801", ("DENIED", "DENIED"), None),
    ("tuple-212", (2, 1, 2), "0a097475706c652d32313210021801200228d00f3801", ("DENIED", "DENIED"), None),
    ("tuple-221", (2, 2, 1), "0a097475706c652d32323110021802200128d00f3801", ("DENIED", "DENIED"), None),
    ("tuple-222", (2, 2, 2), "0a097475706c652d32323210021802200228d00f3801", ("DENIED", "APPLIED"), 2),
)

def json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

def sql_snapshot(raw):
    return {"state": raw["state"], "effects": sorted(raw["effects"], key=lambda r: r["operation_id"])}

def inherited_membership(pid, expected, role):
    try:
        actual = Path("/proc") / str(pid) / "cgroup"
        group = next(line[3:] for line in actual.read_text().splitlines() if line.startswith("0::"))
    except (OSError, StopIteration) as error:
        raise ValueError("Owned process membership unobserved: " + role) from error
    require(group == expected, "Owned process escaped admitted cgroup: " + role)
    return {"role": role, "pid": pid, "controlGroup": group}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apps',type=Path,required=True);p.add_argument('--fixtures',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--semantic-matrix',action='store_true');a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);apps=a.apps.resolve();repo=Path(__file__).resolve().parents[1];hostdir=out/'host'
    hostargs=['python3',linux(repo/'tools/pg_host.py'),'--fixtures',linux(a.fixtures),'--out',linux(hostdir)]
    if os.name=='nt':hostargs=['wsl','-d','Ubuntu-24.04','--']+hostargs
    context=None;memberships=[];matrix_rows=[];matrix_rollback=None
    if a.semantic_matrix:
        require(platform.system() == "Linux", "Flagged profile requires admitted Linux scope")
        context_path = Path(os.environ.get("CE07_PROFILE_CONTEXT", ""))
        require(context_path.is_file() and context_path.stat().st_size <= 65536, "Admitted profile context required")
        context = json.loads(context_path.read_text())
        require(context.get("projectId") == "07" and context.get("profile") == "contract-evolution-07-semantic-matrix-v1", "Wrong project profile")
        memberships.append(inherited_membership(os.getpid(), context["controlGroup"], "integration"))
    hostlog=(out/'host-console.log').open('wb');host=subprocess.Popen(hostargs,stdout=hostlog,stderr=subprocess.STDOUT)
    if context:
        try: memberships.append(inherited_membership(host.pid, context["controlGroup"], "pg-supervisor"))
        except Exception:
            host.terminate();host.wait(timeout=10);hostlog.close();raise
    hostile=out/'unrelated-cwd';hostile.mkdir();(hostile/'appsettings.json').write_text('invalid-json-must-not-be-read')
    children=[];logs=[];checks=[];history=[];expected={};sequence=0;config=None;guard_active=False;guard_proof=None;environment=os.environ.copy();environment['DOTNET_PROCESSOR_COUNT']='2';start=time.monotonic()
    def wait(path,seconds=90):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if path.exists():return
            if (hostdir/'host-error.json').exists() or host.poll() is not None:raise ValueError('Owned PG host failed; inspect sanitized host-error')
            time.sleep(.025)
        raise TimeoutError(path.name)
    def app(role,v):return apps/f'{role}-v{v}'/(f'{role}-v{v}'+('.exe' if os.name=='nt' else ''))
    def binary_snapshot():
        files={}
        for role in ['producer','consumer']:
            for version in [1,2]:
                main=app(role,version);directory=main.parent
                for name in [main.name,f'{role}-v{version}.dll','Core.dll',f'Contract.V{version}.dll']:
                    file=directory/name
                    if file.is_file():files[file.relative_to(apps).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
                require(main.is_file() and (directory/f'{role}-v{version}.dll').is_file(),'Immutable apphost/managed entry required')
                require((directory/f'Contract.V{version}.dll').is_file(),'Immutable contract assembly required')
                if role=='consumer':require((directory/'Core.dll').is_file(),'Immutable consumer Core required')
        return files
    binary_identity=None
    def invoke(role,v,*args,codes=(0,)):
        command=[str(app(role,v)),*map(str,args)]
        if context:
            process=subprocess.Popen(command,cwd=app(role,v).parent,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=environment)
            try:
                memberships.append(inherited_membership(process.pid, context["controlGroup"], role + "-v" + str(v)))
                stdout,stderr=process.communicate(timeout=20)
            except BaseException:
                if process.poll() is None: process.kill()
                process.wait(timeout=10)
                raise
            require(len(stdout.encode("utf-8")) <= 4096 and len(stderr.encode("utf-8")) <= 4096, "Bounded application response")
            r=subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
        else:
            r=subprocess.run(command,cwd=app(role,v).parent,capture_output=True,text=True,env=environment,timeout=20)
        try:result=json.loads(r.stdout)
        except json.JSONDecodeError:raise ValueError('App did not return one JSON response: '+role+' '+str(r.returncode))
        require(r.returncode in codes,'Unexpected process exit '+json.dumps(result))
        history.append({'role':role,'version':v,'command':str(args[0]),'exit':r.returncode,'reply':result});return result
    def control(action):
        nonlocal sequence
        sequence+=1;identity='c'+str(sequence);atomic(hostdir/'control.json',{'id':identity,'action':action});path=hostdir/(identity+'.json');wait(path,45);return json.loads(path.read_text())
    def oracle(raw=None):
        raw=control('oracle') if raw is None else raw;state=raw['state'];rows=raw['effects'];actual={}
        for row in rows:
            ticks=row['amount_ticks'] if 'amount_ticks' in row else row['amount_scaled']//1000
            require(ticks>0 and ('amount_scaled' not in row or row['amount_scaled'] is None or row['amount_scaled']==ticks*1000),'Independent unit invariant')
            require(row['request_hash']==hashlib.sha256(('effect-v1\n'+row['operation_id']+'\nTICKS\n'+str(ticks)+'\n').encode()).hexdigest(),'Independent canonical digest')
            require(0<int(row['receipt'])<=state['total'],'Stored first-result bound');actual[row['operation_id']]=ticks
        require(len(actual)==len(rows) and actual==expected,'Independent effect identity/history mismatch')
        require(state['total']==sum(expected.values()) and state['effects']==len(expected),'Independent SQL conservation')
        history.append({'independentSqlOracle':{'stage':state['stage'],'effects':len(rows),'total':state['total'],'backfilled':state['backfilled']}})
        return raw
    def mark(name):
        require(binary_snapshot()==binary_identity,'Application/core/contract bytes changed across migration stages')
        checks.append(name);print('PASS '+name,flush=True)
    def backfill_all():
        for _ in range(10):
            status=invoke('consumer',2,'backfill','7')['status']
            if status=='BACKFILLED:0':return
            require(status.startswith('BACKFILLED:'),'Backfill stopped without advancing')
        raise ValueError('Demo backfill batch cap exceeded')
    def encode(v,case,identity,ticks):
        path=out/(identity+'-'+case+'-v'+str(v)+'.bin');invoke('producer',v,'encode',case,identity,ticks,path);return path
    def server(v,hook=None):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=environment.copy()
        if hook:
            env['EVOLUTION_LAB_PAUSE']=hook[0];env['EVOLUTION_LAB_HOOK_DIR']=str(hook[1])
        log=(out/('server-'+str(len(children))+'.log')).open('wb');logs.append(log)
        process=subprocess.Popen([str(app('consumer',v)),'serve',str(port)],cwd=hostile,env=env,stdout=log,stderr=subprocess.STDOUT);children.append(process)
        if context: memberships.append(inherited_membership(process.pid, context["controlGroup"], "consumer-server-v" + str(v)))
        until=time.monotonic()+20
        while time.monotonic()<until:
            if process.poll() is not None:raise ValueError('Owned consumer failed at readiness')
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.2):return process,'http://127.0.0.1:'+str(port)
            except OSError:time.sleep(.025)
        raise TimeoutError('Consumer readiness')
    def stop(child):
        if child.poll() is None:child.kill()
        child.wait(timeout=10)
    def send(v,url,file):return invoke('producer',v,'call',url,file,codes=(0,4))
    def resolve_new(v,url,file):
        initial=send(v,url,file)
        if initial['status']!='UNKNOWN':
            require(initial['status']=='APPLIED','New identity unexpectedly returned '+initial['status']);return initial
        digest=hashlib.sha256(file.read_bytes()).hexdigest()
        for attempt in range(1,3):
            require(hashlib.sha256(file.read_bytes()).hexdigest()==digest,'Uncertain request bytes changed')
            resolved=send(v,url,file)
            history.append({'normalUnknownResolution':{'identity':initial['id'],'sameInputSha256':digest,'attempt':attempt,'status':resolved['status']}})
            if resolved['status'] in ['APPLIED','REPLAY']:return resolved
            require(resolved['status']=='UNKNOWN','Uncertain identity resolution denied/conflicted')
        raise ValueError('Bounded same-identity resolution remains UNKNOWN')
    def accepted(v,url,case,identity,ticks,status='APPLIED'):
        file=encode(v,case,identity,ticks);result=resolve_new(v,url,file) if status=='APPLIED' else send(v,url,file);require(result['status'] in ['APPLIED','REPLAY'] if status=='APPLIED' else result['status']==status,(identity,result))
        if status=='APPLIED':expected[identity]=ticks
        return file,result
    def semantic_matrix(oldurl,newurl):
        before_bytes=binary_snapshot()
        for identity,semantic_tuple,hex_frame,statuses,normalized in SEMANTIC_CASES:
            frame=bytes.fromhex(hex_frame)
            require(len(frame) <= 64, "Literal frame bound")
            path=out/(identity+".bin")
            with path.open("xb") as file: file.write(frame)
            record={"id":identity,"tuple":list(semantic_tuple),"amount":2000,"confirmed":True,"frameSha256":hashlib.sha256(frame).hexdigest(),"parsers":[],"consumerResults":[],"sqlComparisons":[]}
            matrix_rows.append(record)
            for producer in (1,2):
                parsed=invoke("producer",producer,"inspect",path)
                projection={key:parsed[key] for key in ("id","semantic","capability","unit","amount","confirmed")}
                record["parsers"].append({"producerVersion":producer,"exit":0,**projection})
                require(projection == {"id":identity,"semantic":semantic_tuple[0],"capability":semantic_tuple[1],"unit":semantic_tuple[2],"amount":"2000","confirmed":True if producer == 2 else None}, "Actual parser projection differs")
            for consumer,url,wanted in zip((1,2),(oldurl,newurl),statuses):
                before=sql_snapshot(oracle())
                reply=send(2,url,path)  # one request, no semantic-matrix UNKNOWN resolution/retry
                record["consumerResults"].append({"consumerVersion":consumer,"exit":history[-1]["exit"],**reply})
                after_raw=control("oracle");after=sql_snapshot(after_raw)
                history.append({"semanticSqlSnapshot":{"identity":identity,"consumer":consumer,"before":before,"after":after}})
                record["sqlComparisons"].append({"consumerVersion":consumer,"comparison":"UNCHANGED" if before == after else "CHANGED","beforeSha256":json_digest(before),"afterSha256":json_digest(after),"stageBefore":before["state"]["stage"],"stageAfter":after["state"]["stage"],"effectsBefore":len(before["effects"]),"effectsAfter":len(after["effects"]),"totalBefore":before["state"]["total"],"totalAfter":after["state"]["total"]})
                require(reply["status"] == wanted and reply["id"] == identity, "Literal semantic outcome differs")
                if wanted == "APPLIED":
                    expected[identity]=normalized
                else:
                    require(before == after, "Denied/replayed semantic request mutated full SQL history")
                oracle(after_raw)
                require(hashlib.sha256(path.read_bytes()).hexdigest() == record["frameSha256"], "Semantic request bytes changed")
        statuses=[r["status"] for case in matrix_rows for r in case["consumerResults"]]
        require((statuses.count("APPLIED"),statuses.count("REPLAY"),statuses.count("DENIED")) == (2,1,13), "Exact matrix outcome counts")
        require(binary_snapshot() == before_bytes == binary_identity, "Matrix changed immutable input")
        mark("literal-mixed-semantic-tuple-matrix-parser-vs-acceptance")

    def save_matrix(status):
        if not context: return
        keys=("projectId","runId","harnessCommit","harnessSha256","profileSha256","runtimeCommit","runtimeTag","archiveSha256")
        value={"schema":"contract-evolution/semantic-matrix/v1","status":status,**{k:context[k] for k in keys},"cases":matrix_rows,"caseCounts":{"frames":len(matrix_rows),"parserObservations":sum(len(r["parsers"]) for r in matrix_rows),"rpcCalls":sum(len(r["consumerResults"]) for r in matrix_rows)},"binaryIdentityBefore":binary_identity,"binaryIdentityAfter":binary_snapshot(),"rollback":matrix_rollback}
        data=json.dumps(value,indent=2)+"\n"
        require(len(data.encode("utf-8")) <= 262144, "Sanitized matrix receipt bound")
        with (out/"semantic-matrix.json").open("x",encoding="utf-8") as file: file.write(data)
        with (out/"membership.private.json").open("x",encoding="utf-8") as file: json.dump(memberships,file)

    try:
        binary_identity=binary_snapshot()
        wait(hostdir/'ready.json');config=json.loads((hostdir/'connection.private.json').read_text());environment['EVOLUTION_LAB_DB']=config['connection']
        require(invoke('consumer',1,'init')['status']=='INITIALIZED_FRESH','Fresh schema')
        old,oldurl=server(1);new,newurl=server(2)
        oversized=out/'oversized.bin';oversized.write_bytes(b'x'*16385)
        require(invoke('producer',1,'inspect',oversized,codes=(2,))['status']=='FAILED_CLOSED','Input cap before parse')
        external=encode(1,'legacy','external-denied',1)
        require(invoke('producer',1,'call','http://example.com:1234',external,codes=(2,))['status']=='FAILED_CLOSED','External endpoint before network')
        mark('ambient-config-isolation-and-bounded-literal-loopback-inputs')
        for producer in [1,2]:
            for consumer,url in [(1,oldurl),(2,newurl)]:
                accepted(producer,url,'additive','matrix-'+str(producer)+str(consumer),producer*10+consumer)
        oracle();mark('actual-four-combination-grpc-matrix-additive-safe')
        if a.semantic_matrix: semantic_matrix(oldurl,newurl)
        for v in [1,2]:
            for case in ['missing','unknown']:
                file=encode(v,case,'deny-'+case+str(v),1)
                for url in [oldurl,newurl]:require(send(v,url,file)['status']=='DENIED','Absent/unknown capability must deny')
        guarded=encode(2,'guarded','guarded',2)
        require(send(2,oldurl,guarded)['status']=='DENIED','Old consumer must reject new semantic units')
        require(send(2,newurl,guarded)['status']=='APPLIED','Confirmed new semantics');expected['guarded']=2
        unsafe=encode(2,'unsafe','unsafe',2);require(send(2,newurl,unsafe)['status']=='DENIED','Absent semantic confirmation')
        oracle();mark('wire-compatible-semantic-change-and-absence-deny')
        preserved=out/'guarded-preserved.bin';lost=out/'guarded-lost.bin'
        invoke('producer',1,'bridge','binary',guarded,preserved);invoke('producer',1,'bridge','json',guarded,lost)
        require(invoke('producer',2,'inspect',preserved)['confirmed'] is True,'Binary unknown-field preservation')
        require(invoke('producer',2,'inspect',lost)['confirmed'] is None,'Actual JSON unknown-field loss')
        require(send(2,newurl,preserved)['status']=='REPLAY' and send(2,newurl,lost)['status']=='DENIED','Roundtrip capability boundary')
        oracle();mark('binary-json-binary-unknown-field-loss-counterexample')
        # Existing legacy rows require a bounded backfill; writers run as independent processes.
        for i in range(34):accepted(1,oldurl,'legacy','seed-'+str(i),i+1)
        uncertain=out/'normal-unknown-after-commit';uncertain.mkdir();normal_child,normal_url=server(1,('after-commit',uncertain))
        accepted(1,normal_url,'legacy','seed-34',35);stop(normal_child)
        require(any('normalUnknownResolution' in event and event['normalUnknownResolution']['identity']=='seed-34' for event in history),'Controlled normal UNKNOWN path was not exercised')
        oracle();mark('bounded-normal-unknown-resolves-byte-identical-business-request')
        oracle()
        require(invoke('consumer',2,'expand')['status']=='EXPAND_COMMITTED','Expand')
        require(invoke('consumer',2,'contract','ack-old-writers-stopped')['status']=='INVARIANT_NOT_READY','Incomplete backfill must stop')
        control('negative-unit-invariant');oracle();mark('expand-and-database-unit-invariant-fail-closed')
        guard=control('install-legacy-input-guard');guard_active=True
        require(guard['triggerNames']==['aa_test_legacy_input_guard','dual_write'],'Fixture guard must precede unchanged product fill trigger')
        control('probe-legacy-input-guard');oracle()
        # Concurrent old and new writers each use immutable producer/consumer executables.
        work=[(v,url,'writer-'+str(v)+'-'+str(i),i+101) for v,url in [(1,oldurl),(2,newurl)] for i in range(4)]
        files=[(v,url,identity,ticks,encode(v,'legacy',identity,ticks)) for v,url,identity,ticks in work]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda item:resolve_new(item[0],item[1],item[4]),files))
        for item,result in zip(files,results):require(result['status'] in ['APPLIED','REPLAY'],'Concurrent writer');expected[item[2]]=item[3]
        oracle();mark('concurrent-old-new-writers-during-expand')
        guard_proof=control('legacy-input-guard-evidence')['legacyInputGuard'];history.append({'legacyInputGuard':guard_proof})
        require(guard_proof['originalFillTriggerPresent'] and guard_proof['rejectedIds']==['writer-1-guard-probe'],'Guard rejects nonnull input, real old writers must not supply scaled')
        require([r['operation_id'] for r in guard_proof['observations']]==['writer-1-'+str(i) for i in range(4)],'Every actual v1 insert observed before fill')
        require(all(r['incoming_scaled'] is None and r['amount_scaled']==r['amount_ticks']*1000 for r in guard_proof['observations']),'Old SQL supplies legacy only; original trigger supplies scaled')
        control('remove-legacy-input-guard');guard_active=False;oracle();mark('legacy-writer-omits-new-column-before-original-trigger')
        require(invoke('consumer',2,'backfill','7')['status']=='BACKFILLED:7','Bounded first batch')
        partial=oracle();require(any(e.get('amount_scaled') is None for e in partial['effects']),'Actual partial backfill')
        # A new process resumes from durable row state; no untrusted high-water cursor.
        backfill_all()
        require(all(e['amount_scaled'] is not None for e in oracle()['effects']),'Restarted backfill invariant')
        mark('bounded-backfill-resumes-across-real-processes')
        stop(new)
        require(invoke('consumer',2,'rollback','ack-new-writers-stopped')['status']=='ROLLBACK_COMMITTED','Demonstrated reversible stage')
        oracle();mark('pre-contract-rollback-preserves-business-history')
        require(invoke('consumer',2,'expand')['status']=='EXPAND_COMMITTED','Re-expand')
        backfill_all()
        new,newurl=server(2)
        # Crash actual consumers in before/after commit windows; never change retry identity.
        for pause,ticks,committed in [('before-commit',17,False),('after-commit',19,True)]:
            identity='crash-'+pause;file=encode(2,'legacy',identity,ticks);hooks=out/identity;hooks.mkdir();child,url=server(2,(pause,hooks))
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(send,2,url,file);wait(hooks/'ready',15);stop(child);reply=future.result(timeout=15)
            require(reply['status']=='UNKNOWN','Disconnect outcome must be unknown')
            if committed:expected[identity]=ticks
            oracle()
            resolved=send(2,newurl,file);require(resolved['status']==('REPLAY' if committed else 'APPLIED'),'Same-identity uncertainty resolution')
            expected[identity]=ticks;oracle()
        mark('before-after-commit-process-crash-same-identity-resolution')
        replay_file=encode(1,'legacy','matrix-11',11);require(send(1,oldurl,replay_file)['status']=='REPLAY','Old receipt before cutover')
        conflict=encode(2,'legacy','matrix-11',999);require(send(2,newurl,conflict)['status']=='CONFLICT','Cross-version digest conflict')
        oracle();mark('cross-version-durable-identity-receipt-and-conflict')
        stop(old)
        require(invoke('consumer',2,'contract','ack-old-writers-stopped')['status']=='CONTRACT_COMMITTED','Explicit irreversible contract')
        rollback_before=sql_snapshot(oracle()) if context else None
        rollback_reply=invoke('consumer',2,'rollback','ack-new-writers-stopped')
        require(rollback_reply['status']=='ROLLBACK_BLOCKED','Post-contract rollback blocked')
        if context:
            rollback_after=sql_snapshot(oracle())
            matrix_rollback={"exit":0,"status":rollback_reply["status"],"stageBefore":rollback_before["state"]["stage"],"stageAfter":rollback_after["state"]["stage"],"sqlUnchanged":rollback_before == rollback_after,"beforeSha256":json_digest(rollback_before),"afterSha256":json_digest(rollback_after)}
            history.append({"rollbackSqlSnapshots":{"before":rollback_before,"after":rollback_after}})
            require(rollback_before == rollback_after and rollback_after["state"]["stage"] == 2, "Blocked rollback changed SQL/schema state")
        old,oldurl=server(1);require(send(1,oldurl,replay_file)['status']=='SCHEMA_UNSUPPORTED','Actual old binary against contracted schema')
        require(send(2,newurl,replay_file)['status']=='REPLAY','New binary preserves old receipt after contract')
        oracle();mark('irreversible-contract-old-binary-stops-without-effects')
        control('restart');require(send(2,newurl,replay_file)['status']=='REPLAY','Ordinary PG restart preserves identity')
        final=oracle();mark('ordinary-pg-restart-retains-effect-history')
        receipt={'status':'PASS','clientOs':platform.system(),'caseCount':len(checks),'cases':checks,'effectCount':len(expected),'total':sum(expected.values()),'finalStage':final['state']['stage'],'legacyInputGuard':guard_proof,'immutableApplicationFiles':binary_identity,'normalUnknownResolutionAttempts':sum('normalUnknownResolution' in event for event in history),'durationSeconds':round(time.monotonic()-start,3)}
        require((len(checks),len(expected),sum(expected.values()),final["state"]["stage"]) == ((15,52,3556,2) if a.semantic_matrix else (14,50,1554,2)), "Exact profile final conservation")
        save_matrix("PASS")
        (out/'history.json').write_text(json.dumps(history,indent=2)+'\n');(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    except Exception as error:
        if context and not (out/"semantic-matrix.json").exists():
            try: save_matrix("INCOMPLETE_NOT_A_PASS")
            except Exception: pass  # retain original diagnostic, never convert failure to success
        if guard_active:
            try:guard_proof=control('legacy-input-guard-evidence')['legacyInputGuard'];history.append({'legacyInputGuardAtFailure':guard_proof})
            except Exception:pass
        (out/'history.incomplete.json').write_text(json.dumps(history,indent=2)+'\n')
        (out/'receipt.incomplete.json').write_text(json.dumps({'status':'INCOMPLETE_NOT_A_PASS','errorType':type(error).__name__,'passedCases':checks,'legacyInputGuard':guard_proof,'scope':'Preserved partial observations; no inferred outcome for unresolved identities'},indent=2)+'\n')
        raise
    finally:
        for child in children:
            if child.poll() is None:stop(child)
        if host.poll() is None:
            try:control('shutdown');host.wait(timeout=30)
            except Exception:host.terminate();host.wait(timeout=10)
        for log in logs:log.close()
        hostlog.close()

if __name__=='__main__':main()
