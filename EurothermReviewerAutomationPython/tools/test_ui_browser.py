"""Browser checks for React controls with deterministic API responses."""
import json
import shutil
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / 'eurothermReviewerAutomationUI'


def main():
    server = subprocess.Popen([shutil.which('node') or r'C:\Program Files\nodejs\node.exe',
                               str(UI / 'node_modules/vite/bin/vite.js'), 'preview',
                               '--host', '127.0.0.1', '--port', '4175', '--strictPort'],
                              cwd=UI, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                with urlopen('http://127.0.0.1:4175', timeout=1):
                    break
            except OSError:
                time.sleep(.25)
        else:
            raise RuntimeError('UI preview did not start')
        records, requests = [], []
        uploaded = None
        batch_fixture = None
        mapping_ready = False
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))

                def api(route):
                    nonlocal uploaded
                    if route.request.url.endswith('/api/stop'):
                        requests.append({'stop': True})
                        records[0]['stopRequested'] = True
                        route.fulfill(status=202, json={'message': 'Stop requested'})
                        return
                    if route.request.url.endswith('/api/upload'):
                        uploaded = dict(name='acceptance.uhh', size=4, sha256='test-input-sha',
                                        path=r'D:\Ceiyone\Input_uhh_files\acceptance.uhh')
                        route.fulfill(status=201, json=uploaded)
                        return
                    if route.request.method == 'POST':
                        body = route.request.post_data_json
                        requests.append(body)
                        record = dict(id=f'test-{len(requests)}', time='2026-10-14T10:00:00Z',
                                      action=body.get('command', 'file:check'), status='Running', message='Automation started',
                                      inputSha256=uploaded['sha256'] if uploaded else None,
                                      details=[{'event': 'fileVerified', 'data': {'size': 123}}])
                        records.insert(0, record)
                        route.fulfill(status=202, json=record)
                    else:
                        route.fulfill(json={'records': records, 'commands': ['batch:scan', 'batch:organize', 'batch:run', 'input:import', 'report', 'file:check', 'workflow:run', 'workflow:channels', 'workflow:pen', 'workflow:messages'], 'batch': batch_fixture,
                                            'workflow': {'ready': False, 'mappingReady': mapping_ready, 'inputDirectory': r'D:\Ceiyone\Input_uhh_files',
                                                         'outputDirectory': r'D:\Ceiyone\Output_report_files',
                                                         'inputFiles': [], 'uploadedFile': uploaded, 'issues': ['25 approved mappings required']}})

                page.route('**/api/*', api)
                page.goto('http://127.0.0.1:4175')
                expect(page.get_by_role('button', name='Run automation', exact=True)).to_be_enabled()
                expect(page.locator('input[type="file"]')).to_have_count(0)
                expect(page.get_by_role('button', name='Start automation', exact=True)).to_be_disabled()
                pen_scenario = page.locator('.scenario-option').filter(has_text='Pen Logs')
                pen_scenario.click()
                expect(pen_scenario).to_have_attribute('aria-pressed', 'true')
                expect(page.get_by_role('button', name='Run automation', exact=True)).to_be_disabled()
                page.get_by_label('Automation action').select_option('workflow:run')
                expect(page.get_by_text('Workflow setup required', exact=True)).to_be_visible()
                expect(page.get_by_role('button', name='Run automation', exact=True)).to_be_disabled()
                page.get_by_label('Automation action').select_option('file:check')
                page.get_by_role('button', name='Run automation', exact=True).click()
                expect(page.get_by_role('button', name='Automation running…')).to_be_disabled()
                expect(page.get_by_role('button', name='Rerun')).to_be_disabled()
                assert requests == [{'command': 'file:check'}]
                records[0].update(status='Success', finished='2026-10-14T10:00:01Z', exitCode=0)
                expect(page.get_by_role('button', name='Rerun')).to_be_enabled(timeout=6000)
                page.get_by_text('Run details', exact=True).click()
                expect(page.get_by_text('Exit code: 0')).to_be_visible()
                expect(page.get_by_text('File verified', exact=True)).to_be_visible()
                expect(page.get_by_role('dialog')).to_be_visible()
                bounds = page.get_by_role('dialog').bounding_box()
                assert abs(bounds['x'] - (page.viewport_size['width'] - bounds['width']) / 2) < 3, 'Details dialog must be centered'
                page.screenshot(path=str(UI / 'ui-details.png'), full_page=True)
                page.get_by_role('button', name='Close run details').click()
                expect(page.get_by_role('dialog')).to_have_count(0)
                page.get_by_role('button', name='Run details', exact=True).click()
                page.keyboard.press('Escape')
                expect(page.get_by_role('dialog')).to_have_count(0)
                expect(page.get_by_role('button', name='Run details', exact=True)).to_be_focused()
                page.get_by_role('button', name='Rerun').click()
                assert requests[-1] == {'rerunId': 'test-1'}
                records[0].update(status='Failed', message='Test failure')
                expect(page.locator('.status-failed')).to_be_visible(timeout=6000)
                page.get_by_label('Filter by status').select_option('Failed')
                expect(page.locator('.status')).to_have_count(1)
                page.get_by_label('Filter by status').select_option('SKIPPED_NO_MESSAGES')
                expect(page.locator('.status')).to_have_count(0)
                page.get_by_label('Filter by status').select_option('Stopped')
                expect(page.locator('.status')).to_have_count(0)
                page.get_by_label('Filter by status').select_option('Failed')
                page.get_by_role('searchbox', name='Search activity').fill('no matching action')
                expect(page.get_by_text('No matching activity', exact=True)).to_be_visible()
                page.get_by_role('button', name='Clear filters').click()
                expect(page.locator('.status')).to_have_count(2)
                page.screenshot(path=str(UI / 'ui-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                expect(page.get_by_role('heading', name='Download history')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile page overflows horizontally'
                page.screenshot(path=str(UI / 'ui-mobile.png'), full_page=True)
                page.get_by_role('button', name='Run details', exact=True).first.click()
                expect(page.get_by_role('dialog')).to_be_visible()
                mobile_bounds = page.get_by_role('dialog').bounding_box()
                assert mobile_bounds['width'] <= 390 and mobile_bounds['x'] >= 0
                page.keyboard.press('Escape')
                expect(page.locator('input[type="file"]')).to_have_count(0)
                records.clear()
                requests.clear()
                mapping_ready = True
                batch_fixture = dict(status='Running', totalFiles=2, completedFiles=1, failedFiles=0, skippedFiles=0,
                                     currentFile=r'D:\Ceiyone\Input_uhh_files\2026\Oct\13\File_02.uhh',
                                     recordingDate='2026-10-13', phase='Preview verified',
                                     profiles={'graph': 'Completed', 'pen-log': 'Running', 'message-log': 'Pending'})
                expect(page.get_by_role('button', name='Start automation', exact=True)).to_be_enabled(timeout=6000)
                page.get_by_role('button', name='Start automation', exact=True).click()
                assert requests[-1] == {'command': 'batch:run'}
                expect(page.locator('.batch-current')).to_contain_text('File_02.uhh')
                expect(page.get_by_role('button', name='Stop automation', exact=True)).to_be_enabled()
                page.get_by_role('button', name='Stop automation', exact=True).click()
                expect(page.get_by_role('button', name='Stop requested', exact=True)).to_be_disabled(timeout=6000)
                assert requests[-1] == {'stop': True}
                assert not errors, errors
                print('PASS: Run, Rerun, statuses, disabled controls, details, search/filter reset, mobile layout without horizontal overflow, no browser errors')
            finally:
                browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == '__main__':
    main()
