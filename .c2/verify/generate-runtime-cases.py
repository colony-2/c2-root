from pathlib import Path
import copy,json,os,sys
local_runtime = '--local-runtime' in sys.argv[2:]
r=Path.cwd(); d=Path(sys.argv[1]).resolve(); d.mkdir(parents=True, exist_ok=True)
source={'cases':[{'id':'baseline','type':'integration_case','runtime':{'cells':{'root':{'file_sources':{}}}},'mocks':{'ops':[{'match':{'op':'command_execution'},'repeat':True,'behavior':{'mode':'passthrough'}}]},'assertions':[{'type':'output_equals','path':'status','value':'passed'},{'type':'cel_true','expr':"size(outputs.artifact_refs) == 6 && repositories.root.clean && repositories.root.new_commits == 0"}]}]}
files=['build.sh','README.md','PURPOSE.md','.c2/config.yaml','.c2/recipes/hooks/build/verify.yaml','scripts','tests']
common={'id':'bounded-hook-caller','input_schema':{'prompt':{'type':'string','default_value':''}},'sequence':[{'id':'hook','include':{'recipe':'cell://.c2/recipes/hooks/build/verify.yaml'},
'inputs':{'api_version':'c2.build-hook/v1','request':'$(touch /tmp/root-verify-injection) `false`','target_directory':'; false',
'candidate':'candidate $(touch /tmp/root-verify-injection)','base':'base `false`','documents':{}},
'expect_outputs':{'type':'object','additionalProperties':False,'required':['api_version','status','summary','artifact_refs'],
'properties':{'api_version':{'type':'string','enum':['c2.build-hook/v1']},'status':{'type':'string','enum':['passed','failed','skipped']},
'summary':{'type':'string','minLength':1,'maxLength':8192},'artifact_refs':{'type':'object','maxProperties':64,'additionalProperties':{'type':'object'}}}}},
{'id':'read_exported_evidence','op':'command_execution','const':True,'artifacts':{'./':'${{ sequence.hook.outputs.artifact_refs }}'},
'inputs':{'env':{'INBOX':'${{ context.environment.op.inbox }}'},'run':'''set -eu
shopt -s nullglob
for file in "$INBOX"/*; do test -s "$file"; done
printf 'Exported native artifacts successfully rebound and read.\\n'
'''}}],
'outputs':{k:'${{ sequence.hook.outputs.'+k+' }}' for k in ['api_version','status','summary','artifact_refs']}}
for setting in ['absent','null','value']:
 wrapper=copy.deepcopy(common)
 if local_runtime: wrapper['execution_needs']={'base':'*'}
 if setting != 'absent': wrapper['sequence'][0]['inputs']['settings']=None if setting=='null' else {'kind':'value','name':'build-settings.json','format':'json','value':{'require_design':False,'prompt_additions':{},'variables':{},'consultations':[]}}
 (d/(setting+'-caller.json')).write_text(json.dumps(wrapper,indent=2))
 cases=[]
 baseline=copy.deepcopy(source['cases'][0]); baseline['id']=setting+'-baseline'
 baseline['runtime']['cells']['root']['file_sources']={p:os.path.relpath(r/p,d) for p in files}
 cases.append(baseline)
 if setting=='absent':
  # Real required command failure, not a mocked aggregate result.
  fail=copy.deepcopy(baseline); fail['id']='mandatory-command-failure'
  broken_hook=json.loads((r/'.c2/recipes/hooks/build/verify.yaml').read_text())
  broken_hook['sequence'][0]['inputs']['run'] += 'echo forced-mandatory-check-failure >&2; exit 7\n'
  fail['runtime']['cells']['root']['files']={'.c2/recipes/hooks/build/verify.yaml':json.dumps(broken_hook)}
  del fail['runtime']['cells']['root']['file_sources']['.c2/recipes/hooks/build/verify.yaml']
  fail['assertions'][0]['value']='failed'
  fail['assertions'].append({'type':'cel_true','expr':"calls.exists(c, c.node_path.endsWith('/acceptance') && c.outputs.success == true)"})
  cases.append(fail)
  for case_name, suffix, timeout in [('native-timeout', 'sleep 5\n', '100ms'), ('missing-tool', 'missing_root_verification_tool\n', '2m')]:
   fail=copy.deepcopy(baseline); fail['id']=case_name
   broken_hook=json.loads((r/'.c2/recipes/hooks/build/verify.yaml').read_text())
   broken_hook['sequence'][0]['inputs']['run'] += suffix
   broken_hook['sequence'][0]['inputs']['timeout']=timeout
   fail['runtime']['cells']['root']['files']={'.c2/recipes/hooks/build/verify.yaml':json.dumps(broken_hook)}
   del fail['runtime']['cells']['root']['file_sources']['.c2/recipes/hooks/build/verify.yaml']
   fail['assertions'][0]['value']='failed'
   fail['assertions'][1]['expr']='repositories.root.clean && repositories.root.new_commits == 0'
   cases.append(fail)
  for name,behavior in [('launch-error',{'mode':'fail','error':{'code':'launch_error','message':'forced launch error'}}),
    ('timeout-result',{'mode':'return','outputs':{'success':False,'exit_code':-1,'timed_out':True},'artifacts':{'catalog.log':'forced timeout'}}),
    ('missing-evidence',{'mode':'return','outputs':{'success':True,'exit_code':0,'timed_out':False}}),
    ('malformed-output',{'mode':'return','outputs':{'stdout':'passed'}})]:
   fail=copy.deepcopy(baseline); fail['id']=name; fail['assertions'][0]['value']='failed'
   fail['assertions'][1]['expr']='repositories.root.clean && repositories.root.new_commits == 0'
   fail['mocks']['ops'].insert(0,{'match':{'node_path':'bounded-hook-caller/hook/root-local-verify/catalog'},'behavior':behavior})
   cases.append(fail)
 if setting=='absent':
  for name, behavior in [('report-launch-error', {'mode':'fail','error':{'message':'forced report launch error'}}), ('missing-report', {'mode':'return','outputs':{'success':True,'exit_code':0,'timed_out':False,'stdout':'passed'}})]:
   fail=copy.deepcopy(baseline); fail['id']=name
   fail['assertions'][0]['value']='failed'
   fail['assertions'][1]['expr']='repositories.root.clean && repositories.root.new_commits == 0'
   fail['mocks']['ops'].insert(0,{'match':{'node_path':'bounded-hook-caller/hook/root-local-verify/summarize'},'behavior':behavior})
   cases.append(fail)
 (d/(setting+'.test.json')).write_text(json.dumps({'recipe':setting+'-caller.json','cases':cases},indent=2))
