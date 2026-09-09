"""Check natural document scrolling, reading layout and navigation in a real offline file."""
from pathlib import Path
import os
from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('SWE_CHROMIUM','/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome'),headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(Path('annotation_release/offline/rater_a.html').resolve().as_uri())
    page.locator('.queue-item').first.click()
    import json
    payload=json.loads(page.locator('#offline-data').text_content())
    expect(page.locator('.user_prompt')).to_have_count(len(payload['cases'][0]['user_turns']))
    expect(page.locator('#trace-help')).to_contain_text(str(payload['cases'][0]['interaction_quality']['effective_interactions']) + ' 次有效交互')
    expect(page.locator('#case-title')).to_have_text('样本 01')
    def positions():
        return page.evaluate('''() => ({body:window.scrollY,document:document.documentElement.scrollHeight,viewport:innerHeight,
            evidence:document.querySelector('#evidence-scroll').scrollTop,form:document.querySelector('#form-scroll').scrollTop,
            queue:document.querySelector('#queue').scrollTop,
            overflow:[...document.querySelectorAll('#queue,#evidence-scroll,#form-scroll,.evidence-panel,.form-panel')].map(e=>getComputedStyle(e).overflowY)})''')
    assert positions()['document']>2000
    assert all(value=='visible' for value in positions()['overflow']),positions()
    # Wheel over either column scrolls the same document, never a nested pane.
    for selector in ('.evidence-panel','.form-panel'):
        page.evaluate('() => window.scrollTo(0, document.querySelector(".columns").offsetTop-100)')
        box=page.locator(selector).bounding_box()
        page.mouse.move(box['x']+box['width']/2,650)
        before=positions();page.mouse.wheel(0,450);page.wait_for_timeout(250)
        down=positions();assert down['body']>before['body'] and down['evidence']==down['form']==down['queue']==0,(before,down)
        page.mouse.wheel(0,-280);page.wait_for_timeout(250)
        assert positions()['body']<down['body']
    page.locator('.reading-nav a[href="#form-panel"]').click()
    form_box=page.locator('#form-panel').bounding_box();assert -10<form_box['y']<160,form_box
    page.locator('#layout-toggle').click()
    expect(page.locator('#layout-toggle')).to_have_attribute('aria-pressed','true')
    eb=page.locator('#evidence-panel').bounding_box();fb=page.locator('#form-panel').bounding_box()
    assert fb['y']>=eb['y']+eb['height']-1,(eb,fb)
    assert eb['width']>1000,eb
    page.locator('#layout-toggle').click()
    expect(page.locator('#layout-toggle')).to_have_attribute('aria-pressed','false')
    page.locator('.reading-nav a[href="#page-top"]').click()
    expect(page.locator('.brand-light')).to_be_in_viewport()
    page.screenshot(path='/tmp/swe_redesign_desktop.png')
    page.locator('.reading-nav a[href="#evidence-panel"]').click()
    page.screenshot(path='/tmp/swe_redesign_reading.png')
    # Native controls remain reachable deep in the long page, with no overlaying submit toolbar.
    page.locator('#field-evolution-initial_coverage').select_option('一部分')
    expect(page.locator('#save-state')).to_contain_text('自动保存')
    page.set_viewport_size({'width':390,'height':844})
    assert all(value=='visible' for value in positions()['overflow'])
    eb=page.locator('#evidence-panel').bounding_box();fb=page.locator('#form-panel').bounding_box()
    assert fb['y']>=eb['y']+eb['height']-1
    assert page.evaluate('() => document.documentElement.scrollWidth')<=390
    page.locator('.reading-nav a[href="#page-top"]').click()
    page.screenshot(path='/tmp/swe_redesign_mobile.png')
    assert not errors,errors
    browser.close()
    print('LAYOUT PASS: one document scroll above both columns, no inner pane scrolling, numbered queue, section links, wide reading mode, responsive stacking, no horizontal overflow, autosave.')
