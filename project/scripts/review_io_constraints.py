"""Validate the narrowly scoped, evidence-bound R6.7 PWM IO review."""
import hashlib,json
from pathlib import Path
EXPECTED=dict(no_clock=0,unconstrained_internal_endpoints=0,no_input_delay=0,no_output_delay=22,partial_input_delay=0,partial_output_delay=0)
REQUIRED={'src/rtl/nh22_axi.sv','board/ax7020_zynq_ports_template.xdc','scripts/create_bd.tcl','sim/tb_nh22_50mhz.sv','sim/results/pwm50.log','build/reports/zynq_neurohead/timing_summary.rpt','build/reports/zynq_neurohead/utilization.rpt'}
def review(root,parsed):
 root=Path(root).resolve();record=json.loads((root/'data/io_constraint_review.json').read_text(encoding='utf-8'))
 if record.get('status')!='accepted_exception' or not record.get('reviewer') or not record.get('rationale'):raise ValueError('Incomplete IO review')
 if record.get('expected_constraint_checks')!=EXPECTED or parsed['constraint_checks']!=EXPECTED:raise ValueError('IO review no longer matches constraint checks')
 evidence=record.get('evidence_sha256',{})
 if set(evidence)!=REQUIRED:raise ValueError('Incomplete or unexpected evidence set')
 for name,want in evidence.items():
  path=(root/name).resolve()
  if root not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest()!=want:raise ValueError('IO review evidence changed: '+name)
 return record['review_id']+': accepted exception; '+record['rationale']+' Evidence: data/io_constraint_review.json'
