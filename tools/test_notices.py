"""Regression gates: a NuGet expression or third-party-only text is not a full license."""
import argparse,json,shutil,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
import notices

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False);repo=Path(__file__).resolve().parents[1]
    class Cases(unittest.TestCase):
        def setUp(self):
            self.work=Path(tempfile.mkdtemp(prefix='notice-test-',dir=a.out));self.root=self.work/'repo';shutil.copytree(repo/'vendor',self.root/'vendor');self.pkg=self.work/'package';self.pkg.mkdir()
            self.record=next(r for r in json.loads((self.root/'vendor/notices/NOTICE-SOURCES.json').read_text())['components'] if r['id']=='Google.Protobuf')
            self.meta=ET.fromstring('<metadata><license type="expression">BSD-3-Clause</license><copyright>Copyright 2015, Google Inc.</copyright></metadata>');self.entry={'sha512':self.record['nugetContentHash']}
        def resolve(self):return notices.resolve(self.root,self.pkg,'Google.Protobuf/3.36.2',self.entry,self.meta)
        def test_full_original_text_and_copyright_resolve(self):
            self.assertGreater(self.resolve()['primary'].stat().st_size,1500);self.assertEqual(self.record['copyright'],self.resolve()['copyright'])
        def test_expression_and_thirdparty_notice_do_not_replace_full_text(self):
            (self.root/'vendor/notices'/self.record['licenseSource']['file']).unlink();(self.pkg/'THIRD-PARTY-NOTICES.txt').write_text('BSD-3-Clause')
            with self.assertRaises(ValueError):self.resolve()
        def test_changed_license_bytes_fail(self):
            (self.root/'vendor/notices'/self.record['licenseSource']['file']).write_text('BSD-3-Clause\n'+'x'*2000)
            with self.assertRaises(ValueError):self.resolve()
        def test_changed_hash_or_copyright_fails(self):
            self.entry['sha512']='attacker'
            with self.assertRaises(ValueError):self.resolve()
            self.entry['sha512']=self.record['nugetContentHash'];self.meta.find('copyright').text='generic MIT owner'
            with self.assertRaises(ValueError):self.resolve()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Cases));receipt={'status':'PASS' if result.wasSuccessful() else 'FAIL','run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors)};(a.out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');raise SystemExit(0 if result.wasSuccessful() else 1)
if __name__=='__main__':main()
