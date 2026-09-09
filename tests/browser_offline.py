"""Optional end-to-end check: PYTHONPATH=src:tests python tests/browser_offline.py.
Requires Playwright and a Chromium executable via SWE_CHROMIUM (outside runtime deps).
"""
from copy import deepcopy
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from test_human_team import TeamTests
from test_human_simple import annotation
from swe_chat_analysis.human_team import merge, load_bundle
from swe_chat_analysis.human_simple import costs, summarize

fixture=TeamTests();fixture.setUp()
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('SWE_CHROMIUM','/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome'), headless=True,args=['--no-sandbox'])
        errors=[];requests=[]
        context=browser.new_context(accept_downloads=True)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url))
        path=fixture.bundle/'offline'/'rater_a.html'
        page.goto(path.as_uri())
        expect(page.locator('.queue-item')).to_have_count(30)
        page.locator('.queue-item').first.click()
        expect(page.locator('.user_prompt pre')).to_have_count(8)
        expect(page.locator('.agent-fold[open]')).to_have_count(0)
        expect(page.locator('#annotation-form textarea')).to_have_count(0)
        expect(page.locator('#field-gap-driver')).to_have_count(1)
        page.locator('#field-evolution-new_requirements').select_option('有')
        expect(page.locator('#field-evolution-source')).to_be_visible()
        page.locator('#field-evolution-source').select_option('用户偏好')
        expect(page.locator('#field-evolution-first_new_turn')).to_have_count(0)
        page.locator('#field-evolution-new_requirements').select_option('没有')
        expect(page.locator('#field-evolution-source')).to_have_count(0)
        page.locator('#field-evolution-initial_coverage').select_option('一部分')
        expect(page.locator('#save-state')).to_contain_text('自动保存')
        page.reload();page.locator('.queue-item').first.click()
        expect(page.locator('#field-evolution-initial_coverage')).to_have_value('一部分')
        page.locator('summary').filter(has_text='高级').click()
        bad=annotation();bad['evolution']['source']=None
        page.locator('#json-editor').fill(json.dumps(bad,ensure_ascii=False));page.locator('#apply-json').click();page.locator('#submit').click()
        expect(page.locator('#message')).to_contain_text('请选择需求来源')
        page.locator('#json-editor').fill(json.dumps(annotation(),ensure_ascii=False));page.locator('#apply-json').click();page.locator('#submit').click()
        expect(page.locator('#save-state')).to_contain_text('已提交')
        page.locator('.queue-item').nth(1).click();page.locator('#field-evolution-initial_coverage').select_option('全部')
        with page.expect_download() as d:page.locator('#backup-progress').click()
        backup=fixture.root/'backup.json';d.value.save_as(backup)
        assert json.loads(backup.read_text())['records']
        context.close()
        # Restore in a new browser profile: file path/origin storage is not required.
        context=browser.new_context(accept_downloads=True);page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url))
        page.on('dialog',lambda d:d.accept())
        page.goto(path.as_uri());expect(page.locator('.queue-item')).to_have_count(30)
        page.locator('#restore-progress').set_input_files(str(backup));expect(page.locator('#message')).to_contain_text('已导入进度')
        page.locator('.queue-item').nth(1).click();expect(page.locator('#field-evolution-initial_coverage')).to_have_value('全部')
        page.locator('.queue-item').first.click();expect(page.locator('#save-state')).to_contain_text('已提交')
        # Reject wrong-owner restore without overwriting any records.
        wrong=json.loads(backup.read_text());wrong['annotator']='rater_b'
        wrong_path=fixture.root/'wrong.json';wrong_path.write_text(json.dumps(wrong))
        page.locator('#restore-progress').set_input_files(str(wrong_path));expect(page.locator('#message')).to_contain_text('导入失败')
        inputs=[]
        for rater in ('rater_a','rater_b','rater_c'):
            page.goto((fixture.bundle/'offline'/f'{rater}.html').as_uri())
            expect(page.locator('.queue-item')).to_have_count(40 if rater=='rater_c' else 30)
            page.evaluate('''async ({rater, answer}) => {
              const tasks=await window.offlineAPI('/api/tasks?annotator='+rater);
              for(const [index,task] of tasks.cases.entries()){
                const caseAnswer=structuredClone(answer);
                if(index % 3) Object.assign(caseAnswer.evolution,{new_requirements:index % 3 === 1 ? "没有" : "无法判断",source:null});
                const view=await window.offlineAPI('/api/case?annotator='+rater+'&case_id='+task.case_id+'&stage=review');
                await window.offlineAPI('/api/save',{annotator:rater,case_id:task.case_id,stage:'review',revision:view.revision,annotation:caseAnswer,complete:true});
              }
            }''',dict(rater=rater,answer=annotation()))
            with page.expect_download() as d:page.locator('#export').click()
            output=fixture.root/f'submission_{rater}.json';d.value.save_as(output);inputs.append(output)
            value=json.loads(output.read_text());assert value['delivery']['complete']
        result=merge(fixture.bundle,inputs,fixture.root/'offline_merged')
        assert result['run_completeness']['completed']==100
        _,cases=load_bundle(fixture.bundle)
        for path in inputs:
            payload=json.loads(path.read_text());rows=payload['annotations']['review']
            for row in rows:assert row['metrics']==costs(cases[row['session_id']],row['annotation'])
            assert payload['summary']['cost_comparison']==summarize(rows)['cost_comparison']
        assert not errors,errors
        assert not [url for url in requests if url.startswith(('https:','http:'))],requests
        # Storage-denied mode must preserve edits in memory and offer a backup.
        denied=browser.new_context(accept_downloads=True)
        denied.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw new DOMException('Denied','SecurityError')}});")
        dp=denied.new_page();dp.on('dialog',lambda d:d.accept())
        dp.goto((fixture.bundle/'offline'/'rater_b.html').as_uri());expect(dp.locator('.queue-item')).to_have_count(30)
        dp.locator('.queue-item').first.click();dp.locator('#field-evolution-initial_coverage').select_option('没有')
        expect(dp.locator('#save-state')).to_contain_text('仅保存在本页内存')
        with dp.expect_download() as d:dp.locator('#backup-progress').click()
        fallback=json.loads(Path(d.value.path()).read_text())
        assert next(iter(fallback['records'].values()))['annotation']['evolution']['initial_coverage']=='没有'
        browser.close()
        print('OFFLINE PASS: file://, 8 prompts, autosave/reload, validation, backup/restore, wrong-owner rejection, 30/30/40 JSON merge, Python metric parity, no network, storage-denied fallback.')
finally:fixture.doCleanups()
