"""Fresh non-root loopback PostgreSQL fixture; no install/system service.
Adapted from the public MIT Fenced Shard Ownership Lab pg lifecycle profile.
Only this supervisor's own data/processes are controlled. Never upload private output.
"""
import argparse,json,os,re,secrets,socket,subprocess,tempfile,time
from pathlib import Path

def publish(path,data):
    temporary=path.with_suffix('.partial');temporary.write_text(json.dumps(data)+'\n');os.replace(temporary,path)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixtures',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if os.name!='posix' or os.getuid()==0:raise ValueError('Existing non-root Linux user required')
    root=a.fixtures.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    scratch=Path(tempfile.mkdtemp(prefix='portfolio-contract-'));os.chmod(scratch,0o700)
    pg=root/'root/usr/lib/postgresql/18/bin';env=os.environ.copy();env['LD_LIBRARY_PATH']=str(root/'root/usr/lib/x86_64-linux-gnu')
    secret=secrets.token_hex(24);admin=secrets.token_hex(24);pw=scratch/'admin-password';pw.write_text(admin);os.chmod(pw,0o600)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    started=time.monotonic();running=False
    def command(args,extra=None,expected=0):
        local=env.copy();local.update(extra or {})
        r=subprocess.run(list(map(str,args)),env=local,capture_output=True,text=True,timeout=60)
        if r.returncode!=expected:
            raise RuntimeError('Owned fixture command failed: '+Path(str(args[0])).name+' '+r.stderr[-1000:].replace(secret,'[redacted]').replace(admin,'[redacted]'))
        return r.stdout
    def sql(text):return command([pg/'psql','-X','-A','-t','-v','ON_ERROR_STOP=1','-h','127.0.0.1','-p',port,'-U','lab_admin','-d','contract_lab','-c',text],{'PGPASSWORD':admin})
    def expect_sql_error(text,message):
        local=env.copy();local['PGPASSWORD']=admin
        result=subprocess.run(list(map(str,[pg/'psql','-X','-v','ON_ERROR_STOP=1','-v','VERBOSITY=verbose','-h','127.0.0.1','-p',port,'-U','lab_admin','-d','contract_lab','-c',text])),env=local,capture_output=True,text=True,timeout=30)
        if result.returncode!=1 or 'P0001' not in result.stderr or message not in result.stderr:raise ValueError('Expected named synthetic trigger rejection absent')
    def legacy_guard_evidence():
        observed=json.loads(sql("SELECT COALESCE(json_agg(r ORDER BY operation_id),'[]'::json) FROM (SELECT a.operation_id,a.incoming_scaled,e.amount_ticks,e.amount_scaled FROM evolution_v1.test_legacy_input_audit a JOIN evolution_v1.effects e USING(operation_id)) r").strip())
        rejected=set()
        with (out/'postgres.log').open(encoding='utf-8',errors='replace') as log:
            for line in log:
                match=re.search(r'ERROR:\s+OLD_WRITER_SENT_SCALED:(writer-1-[a-z0-9-]{1,64})',line)
                if match:rejected.add(match.group(1))
        return {'observations':observed,'rejectedIds':sorted(rejected)[:32],'originalFillTriggerPresent':sql("SELECT count(*) FROM pg_trigger WHERE tgrelid='evolution_v1.effects'::regclass AND tgname='dual_write' AND NOT tgisinternal").strip()=='1'}
    def start():
        nonlocal running
        command([pg/'pg_ctl','-D',scratch/'pg','-l',out/'postgres.log','-o',f'-h 127.0.0.1 -p {port} -k {scratch} -c shared_buffers=64MB -c max_connections=24 -c max_wal_size=256MB -c jit=off','-w','-t','30','start']);running=True
    def stop():
        nonlocal running
        if running:command([pg/'pg_ctl','-D',scratch/'pg','-w','-t','15','-m','fast','stop']);running=False
    try:
        command([pg/'initdb','-D',scratch/'pg','--username=lab_admin','--auth-host=scram-sha-256','--auth-local=peer','--pwfile',pw,'--no-locale','--encoding=UTF8']);start()
        for statement in ["CREATE ROLE contract_lab LOGIN PASSWORD '"+secret+"'","CREATE DATABASE contract_lab OWNER contract_lab"]:
            command([pg/'psql','-X','-v','ON_ERROR_STOP=1','-h','127.0.0.1','-p',port,'-U','lab_admin','-d','postgres','-c',statement],{'PGPASSWORD':admin})
        publish(out/'connection.private.json',{'connection':f'Host=127.0.0.1;Port={port};Username=contract_lab;Password={secret};Database=contract_lab'})
        os.chmod(out/'connection.private.json',0o600);publish(out/'ready.json',{'status':'READY','port':port,'scratch':str(scratch),'physicalFaultDomains':1})
        while time.monotonic()-started<900:
            if sum(f.stat().st_size for f in out.glob('*.log'))>256*1024*1024:raise ValueError('Log cap')
            request=out/'control.json'
            if not request.exists():time.sleep(.025);continue
            data=json.loads(request.read_text());request.unlink();identity=data['id'];action=data['action']
            if not isinstance(identity,str) or not identity.isascii() or not identity.isalnum() or len(identity)>64:raise ValueError('Mailbox identity')
            result={'status':'OK','id':identity}
            if action=='oracle':
                result['state']=json.loads(sql("SELECT row_to_json(s) FROM evolution_v1.state s").strip())
                result['effects']=json.loads(sql("SELECT COALESCE(json_agg(e ORDER BY operation_id),'[]'::json) FROM evolution_v1.effects e").strip())
            elif action=='negative-unit-invariant':
                expect_sql_error("INSERT INTO evolution_v1.effects(operation_id,request_hash,amount_ticks,amount_scaled,receipt) VALUES('corrupt','bad',1,2000,'bad')",'UNIT_INVARIANT')
            elif action=='install-legacy-input-guard':
                if sql('SELECT stage FROM evolution_v1.state WHERE id').strip()!='1':raise ValueError('Guard is expanded-fixture-only')
                sql("SET ROLE contract_lab; CREATE TABLE evolution_v1.test_legacy_input_audit(operation_id text PRIMARY KEY,incoming_scaled bigint CHECK(incoming_scaled IS NULL)); CREATE FUNCTION evolution_v1.test_legacy_input_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.operation_id LIKE 'writer-1-%' THEN IF NEW.amount_scaled IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='OLD_WRITER_SENT_SCALED:'||NEW.operation_id; END IF; INSERT INTO evolution_v1.test_legacy_input_audit VALUES(NEW.operation_id,NEW.amount_scaled); END IF; RETURN NEW; END $$; CREATE TRIGGER aa_test_legacy_input_guard BEFORE INSERT ON evolution_v1.effects FOR EACH ROW EXECUTE FUNCTION evolution_v1.test_legacy_input_guard(); RESET ROLE;")
                result['triggerNames']=json.loads(sql("SELECT json_agg(tgname ORDER BY tgname) FROM pg_trigger WHERE tgrelid='evolution_v1.effects'::regclass AND NOT tgisinternal").strip())
            elif action=='probe-legacy-input-guard':
                expect_sql_error("INSERT INTO evolution_v1.effects(operation_id,request_hash,amount_ticks,amount_scaled,receipt) VALUES('writer-1-guard-probe','synthetic-probe',1,1000,'synthetic-probe')",'OLD_WRITER_SENT_SCALED:writer-1-guard-probe')
            elif action=='legacy-input-guard-evidence':result['legacyInputGuard']=legacy_guard_evidence()
            elif action=='remove-legacy-input-guard':
                sql('DROP TRIGGER aa_test_legacy_input_guard ON evolution_v1.effects; DROP FUNCTION evolution_v1.test_legacy_input_guard(); DROP TABLE evolution_v1.test_legacy_input_audit;')
            elif action=='restart':stop();start()
            elif action=='shutdown':publish(out/(identity+'.json'),result);break
            else:raise ValueError('Unsupported named fixture operation')
            publish(out/(identity+'.json'),result)
        else:raise TimeoutError('Bounded owned fixture expired')
    except Exception as error:
        publish(out/'host-error.json',{'status':'FAILED','type':type(error).__name__,'detail':str(error)[:1200]});raise
    finally:
        stop()
        # Preserve owned scratch and logs for review; do not recursively remove anything.

if __name__=='__main__':main()
