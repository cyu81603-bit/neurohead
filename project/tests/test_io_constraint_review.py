"""The IO review must fail closed when its scope or evidence changes."""
import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from review_io_constraints import review,EXPECTED,REQUIRED
class ReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup);(self.root/'data').mkdir()
  evidence={}
  for name in REQUIRED:
   p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode());evidence[name]=hashlib.sha256(p.read_bytes()).hexdigest()
  self.record=dict(review_id='fixture',status='accepted_exception',reviewer='test',rationale='fixture',expected_constraint_checks=EXPECTED,evidence_sha256=evidence);self.save()
 def save(self): (self.root/'data/io_constraint_review.json').write_text(json.dumps(self.record),encoding='utf-8')
 def test_matching_review(self): self.assertIn('accepted exception',review(self.root,dict(constraint_checks=EXPECTED)))
 def test_extra_gap_rejected(self):
  c=dict(EXPECTED,no_input_delay=1)
  with self.assertRaises(ValueError):review(self.root,dict(constraint_checks=c))
 def test_changed_count_rejected(self):
  with self.assertRaises(ValueError):review(self.root,dict(constraint_checks=dict(EXPECTED,no_output_delay=23)))
 def test_stale_evidence_rejected(self):
  (self.root/'src/rtl/nh22_axi.sv').write_bytes(b'changed')
  with self.assertRaises(ValueError):review(self.root,dict(constraint_checks=EXPECTED))
 def test_pending_rejected(self):
  self.record['status']='pending';self.save()
  with self.assertRaises(ValueError):review(self.root,dict(constraint_checks=EXPECTED))
 def test_missing_evidence_rejected(self):
  self.record['evidence_sha256'].pop('scripts/create_bd.tcl');self.save()
  with self.assertRaises(ValueError):review(self.root,dict(constraint_checks=EXPECTED))
if __name__=='__main__':unittest.main(verbosity=2)
