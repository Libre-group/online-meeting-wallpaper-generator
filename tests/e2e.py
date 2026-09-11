#!/usr/bin/env python3
"""
ブラウザでの動作確認（結合テスト）

index.html を実際の Chromium で開き、次を確認する。
  - JavaScript のエラーが出ないこと
  - レイアウト A〜E すべてで 1920×1080 の画像が書き出せること
  - 書き出した画像に入った QR コードが実際に読み取れること
  - 会議ツールがタイルを 4:3 / 1:1 に切り抜いても QR が残ること（セーフゾーンの検証）
  - テンプレートに個人情報（氏名・肩書・連絡先など）が含まれないこと

必要なもの:
    pip install playwright opencv-python-headless numpy
    playwright install chromium     （Chromium が別途ある場合は CHROME 環境変数で指定）

実行:
    python3 tests/e2e.py
"""
import os, sys, json, tempfile
import numpy as np
import cv2
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, 'index.html')
CHROME = os.environ.get('CHROME')  # 例: /opt/pw-browsers/chromium-1194/chrome-linux/chrome

failures = []
def check(name, ok, detail=''):
    print(('  OK  ' if ok else '  NG  ') + name + (f' — {detail}' if detail and not ok else ''))
    if not ok:
        failures.append(name)

def make_assets(tmp):
    """検証用のベース画像とロゴを生成する"""
    base = np.zeros((900, 1600, 3), np.uint8)
    for y in range(900):
        base[y, :, 0] = 110 + y // 20
        base[y, :, 1] = 70 + y // 12
        base[y, :, 2] = 40 + y // 8
    cv2.circle(base, (1200, 300), 180, (200, 220, 230), -1)
    cv2.imwrite(f'{tmp}/base.png', base)
    logo = np.zeros((200, 600, 4), np.uint8)
    cv2.rectangle(logo, (10, 60), (590, 140), (255, 255, 255, 255), -1)
    cv2.putText(logo, 'LOGO', (60, 125), cv2.FONT_HERSHEY_DUPLEX, 2.0, (90, 40, 20, 255), 4)
    cv2.imwrite(f'{tmp}/logo.png', logo)

QR_URL = 'https://example.com/contact?from=meet'

def main():
    tmp = tempfile.mkdtemp(prefix='bg-e2e-')
    make_assets(tmp)
    errors = []

    with sync_playwright() as p:
        launch = {'executable_path': CHROME} if CHROME else {}
        browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={'width': 1500, 'height': 1200})
        page.on('console', lambda m: errors.append(f'console.{m.type}: {m.text}') if m.type == 'error' else None)
        page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        page.goto('file://' + PAGE)
        page.wait_for_timeout(600)

        page.set_input_files('#baseFile', f'{tmp}/base.png')
        page.set_input_files('#logoFile', f'{tmp}/logo.png')
        page.fill('#f_company', '〇〇法律事務所')
        page.fill('#f_qual', '弁護士')
        page.fill('#f_name', '山田 太郎')
        page.fill('#f_namesub', 'TARO YAMADA')
        page.fill('#f_title', '代表弁護士 / 企業法務部')
        page.fill('#f_contact', '011-000-0000 / example.com')
        page.fill('#f_catch', 'はじめの一歩を、ともに。\n労務のご相談はお気軽に。')
        page.fill('#f_qr', QR_URL)
        page.wait_for_timeout(1200)

        det = cv2.QRCodeDetector()
        for lay in ['A', 'B', 'C', 'D', 'E']:
            page.click(f'#layouts button[data-layout="{lay}"]')
            page.wait_for_timeout(400)
            with page.expect_download() as dl:
                page.click('#download')
            path = f'{tmp}/out_{lay}.png'
            dl.value.save_as(path)
            img = cv2.imread(path)
            check(f'レイアウト{lay}: 1920×1080 で書き出せる', img.shape[:2] == (1080, 1920), str(img.shape))
            h, w = img.shape[:2]
            for label, ratio in [('16:9', 16 / 3 * 3 / 3), ('4:3', 4 / 3), ('1:1', 1.0)]:
                sw = min(w, int(h * ratio))
                x0 = (w - sw) // 2
                txt, *_ = det.detectAndDecode(img[:, x0:x0 + sw])
                check(f'レイアウト{lay}: {label} に切り抜いてもQRが読める', txt == QR_URL, repr(txt[:40]))

        # JPEG / 4K の書き出し
        page.click('#layouts button[data-layout="A"]')
        page.select_option('#fmtSel', 'jpeg')
        page.select_option('#sizeSel', '3840x2160')
        page.wait_for_timeout(1500)
        with page.expect_download() as dl:
            page.click('#download')
        dl.value.save_as(f'{tmp}/out_4k.jpg')
        img4k = cv2.imread(f'{tmp}/out_4k.jpg')
        check('4K JPEG で書き出せる', img4k.shape[:2] == (2160, 3840), str(img4k.shape))
        check('推定ファイルサイズが表示される', 'MB' in page.text_content('#sizeInfo'))
        page.select_option('#fmtSel', 'png')
        page.select_option('#sizeSel', '1920x1080')

        # プレビュー上のドラッグで位置が変わる
        box = page.locator('#stage').bounding_box()
        page.mouse.move(box['x'] + box['width'] * 0.72, box['y'] + box['height'] * 0.80)
        page.mouse.down()
        page.mouse.move(box['x'] + box['width'] * 0.60, box['y'] + box['height'] * 0.60, steps=8)
        page.mouse.up()
        page.wait_for_timeout(300)
        moved = page.text_content('#adjXV') != '0%' or page.text_content('#adjYV') != '0%'
        check('プレビュー上のドラッグで配置が動く', moved)

        # テンプレートに個人情報が入らない
        with page.expect_download() as dl:
            page.click('#tplSave')
        dl.value.save_as(f'{tmp}/tpl.json')
        tpl = json.load(open(f'{tmp}/tpl.json'))
        personal = [k for k in ('name', 'namesub', 'title', 'qual', 'contact', 'qr') if tpl['text'].get(k)]
        check('テンプレートに個人情報が含まれない', not personal, str(personal))
        check('テンプレートに会社名が含まれる', tpl['text'].get('company') == '〇〇法律事務所')

        browser.close()

    check('JavaScript のエラーが出ない', not errors, '; '.join(errors[:3]))
    print(f'\n{"失敗 " + str(len(failures)) + " 件" if failures else "すべて成功"}')
    return 1 if failures else 0

if __name__ == '__main__':
    sys.exit(main())
