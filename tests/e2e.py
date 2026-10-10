#!/usr/bin/env python3
"""
ブラウザでの動作確認（結合テスト）

index.html を実際の Chromium で開き、次を確認する。
  - JavaScript のエラーが出ないこと
  - レイアウト A〜E すべてで 1920×1080 の画像が書き出せること
  - 書き出した画像に入った QR コードが実際に読み取れること
  - 会議ツールがタイルを 4:3 / 1:1 に切り抜いても QR が残ること（セーフゾーンの検証）
  - テンプレートに個人情報（氏名・肩書・連絡先など）が含まれないこと
  - 縦横比の違う画像を読み込んだとき、自動で「画像全体を入れる」に切り替わること
  - 既定テンプレートを埋め込んだ HTML が、開いた時点で設定済みになること
  - 会社名を改行で複数行書けること（4行まで）
  - 埋め込みHTMLに背景画像が入り、2回目以降に開いても残ること
  - マスコット画像を四隅に置け、左右反転でき、埋め込みにも引き継がれること
  - 各ブロックを9か所に置け、下端まで下げてもはみ出さないこと
  - 重ねる色・パネル色・配色プリセットが効くこと
  - 選択中ブロックの点線が、プレビューには出て書き出した画像には入らないこと

必要なもの:
    pip install playwright opencv-python-headless numpy
    playwright install chromium     （Chromium が別途ある場合は CHROME 環境変数で指定）

実行:
    python3 tests/e2e.py
"""
import os, re, sys, json, tempfile
import numpy as np
import cv2
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'index.html')
EMBED_RE = r'(<script type="application/json" id="embedded-template">)(.*?)(</script>)'
CHROME = os.environ.get('CHROME')  # 例: /opt/pw-browsers/chromium-1194/chrome-linux/chrome

failures = []
def check(name, ok, detail=''):
    print(('  OK  ' if ok else '  NG  ') + name + (f' — {detail}' if detail and not ok else ''))
    if not ok:
        failures.append(name)

def plain_copy(tmp):
    """既定テンプレートを外したコピーを作る。
    配布用の index.html には会社の既定テンプレートが埋め込まれていることがあり、
    そのままだと「氏名の差し替えのみ」モードで開いて設定欄が隠れ、画像も最初から
    入っている。テストは工場出荷状態から始めたいので、埋め込みだけ空にする。"""
    html = open(SRC, encoding='utf-8').read()
    clean = re.sub(EMBED_RE, lambda m: m.group(1) + 'null' + m.group(3), html, flags=re.S)
    path = os.path.join(tmp, 'index_plain.html')
    open(path, 'w', encoding='utf-8').write(clean)
    return path


def embedded_default():
    """配布用 index.html に埋め込まれている既定テンプレート（無ければ None）"""
    raw = re.search(EMBED_RE, open(SRC, encoding='utf-8').read(), re.S).group(2).strip()
    return None if raw == 'null' else json.loads(raw)


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
    # 縦横比の確認用。赤枠と中央十字を入れ、切り取られた範囲が分かるようにする
    for name, (w, h) in {'4x3': (1600, 1200), 'portrait': (900, 1600), '16x9': (1920, 1080)}.items():
        im = np.full((h, w, 3), 200, np.uint8)
        cv2.rectangle(im, (0, 0), (w - 1, h - 1), (0, 0, 255), 24)
        cv2.line(im, (0, h // 2), (w, h // 2), (255, 0, 0), 8)
        cv2.line(im, (w // 2, 0), (w // 2, h), (255, 0, 0), 8)
        cv2.imwrite(f'{tmp}/ar_{name}.png', im)
    # 背景が引き継がれたか一目で分かる単色画像
    green = np.zeros((1080, 1920, 3), np.uint8)
    green[:, :] = (40, 140, 40)
    cv2.imwrite(f'{tmp}/green.png', green)
    # 左半分=赤 / 右半分=青 の非対称なマスコット（左右反転を検出できる）
    mas = np.zeros((400, 300, 4), np.uint8)
    cv2.rectangle(mas, (0, 100), (150, 300), (0, 0, 255, 255), -1)
    cv2.rectangle(mas, (150, 100), (300, 300), (255, 0, 0, 255), -1)
    cv2.imwrite(f'{tmp}/mascot.png', mas)

QR_URL = 'https://example.com/contact?from=meet'

def main():
    tmp = tempfile.mkdtemp(prefix='bg-e2e-')
    make_assets(tmp)
    PAGE = plain_copy(tmp)
    errors = []

    with sync_playwright() as p:
        launch = {'executable_path': CHROME} if CHROME else {}
        browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={'width': 1500, 'height': 1200})
        page.on('console', lambda m: errors.append(f'console.{m.type}: {m.text}') if m.type == 'error' else None)
        page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        page.goto('file://' + PAGE)
        page.wait_for_timeout(600)

        def set_range(rid, val):
            page.evaluate(f"() => {{ const e = document.getElementById('{rid}'); e.value = {val}; e.dispatchEvent(new Event('input')); }}")

        def set_color(cid, val):
            page.evaluate(f"() => {{ const e = document.getElementById('{cid}'); e.value = '{val}'; e.dispatchEvent(new Event('input')); }}")


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

        # --- 縦横比の違う画像の扱い ---
        print('[画像の合わせ方]')
        page.set_input_files('#baseFile', f'{tmp}/ar_portrait.png')
        page.wait_for_timeout(800)
        check('縦長画像で自動的に「画像全体を入れる」になる', page.input_value('#fit') == 'contain',
              page.input_value('#fit'))
        check('切り取り率を知らせるメッセージが出る', '約68%' in page.text_content('#baseNotice'),
              page.text_content('#baseNotice')[:60])
        check('読み込んだ画像の縦横比を表示する', '9:16' in page.text_content('#baseInfo'),
              page.text_content('#baseInfo'))
        with page.expect_download() as dl:
            page.click('#download')
        dl.value.save_as(f'{tmp}/ar_out.png')
        im = cv2.imread(f'{tmp}/ar_out.png')
        red = ((im[:, :, 2].astype(int) - im[:, :, 0]) > 60) & ((im[:, :, 2].astype(int) - im[:, :, 1]) > 60)
        xs = np.nonzero(red.any(axis=0))[0]
        check('縦長画像の左右の端まで写っている',
              len(xs) > 0 and xs.min() > 50 and xs.max() < im.shape[1] - 50,
              f'x={xs.min() if len(xs) else "-"}..{xs.max() if len(xs) else "-"}')
        page.click('#fitCover')
        page.wait_for_timeout(300)
        check('「全面に広げる」で戻せる', page.input_value('#fit') == 'cover')
        check('ズームを100%未満にできる', page.get_attribute('#zoom', 'min') == '25')
        page.set_input_files('#baseFile', f'{tmp}/ar_16x9.png')
        page.wait_for_timeout(800)
        check('16:9 の画像では切り替えない', page.input_value('#fit') == 'cover', page.input_value('#fit'))
        check('16:9 の画像ではメッセージを出さない', page.locator('#baseNotice').is_hidden())
        page.set_input_files('#baseFile', f'{tmp}/base.png')
        page.wait_for_timeout(600)

        # --- 既定テンプレートを埋め込んだ HTML ---
        print('[既定テンプレートの埋め込み]')
        page.click('#layouts button[data-layout="C"]')
        page.set_input_files('#baseFile', f'{tmp}/green.png')
        page.set_input_files('#mascotFile', f'{tmp}/mascot.png')
        page.click('#mascotPos button[data-pos="br"]')
        page.wait_for_timeout(800)   # チェックは入れない（常に含まれるのが正しい挙動）
        with page.expect_download() as dl:
            page.click('#tplEmbed')
        embedded_dir = os.path.join(tmp, 'embedded')
        os.makedirs(embedded_dir, exist_ok=True)
        embedded_page = os.path.join(embedded_dir, 'index.html')
        dl.value.save_as(embedded_page)
        check('HTML が書き出される', os.path.getsize(embedded_page) > 50_000,
              f'{os.path.getsize(embedded_page)} bytes')

        # localStorage のない状態（別のブラウザ）で開き直す
        ctx2 = browser.new_context(viewport={'width': 1500, 'height': 1200})
        p2 = ctx2.new_page()
        p2.on('console', lambda m: errors.append(f'embedded console.{m.type}: {m.text}') if m.type == 'error' else None)
        p2.on('pageerror', lambda e: errors.append(f'embedded pageerror: {e}'))
        p2.goto('file://' + embedded_page)
        p2.wait_for_timeout(1200)
        check('開いた時点で会社名が入っている', p2.input_value('#f_company') == '〇〇法律事務所',
              p2.input_value('#f_company'))
        check('開いた時点でレイアウトが引き継がれている',
              p2.get_attribute('#layouts button[data-layout="C"]', 'aria-pressed') == 'true')
        check('氏名は引き継がれない（個人情報）', p2.input_value('#f_name') == '', repr(p2.input_value('#f_name')))
        check('連絡先も引き継がれない', p2.input_value('#f_contact') == '', repr(p2.input_value('#f_contact')))
        check('「氏名の差し替えのみ」モードで開く', p2.get_attribute('#modeName', 'aria-pressed') == 'true')
        check('既定テンプレートが入っている旨の案内が出る', not p2.locator('#embeddedInfo').is_hidden())
        p2.click('#modeFull')
        p2.wait_for_timeout(300)
        check('テンプレート編集モードに戻せる', p2.locator('#accentColor').is_visible())
        p2.fill('#f_name', '鈴木 一郎')
        p2.wait_for_timeout(600)
        with p2.expect_download() as dl:
            p2.click('#download')
        dl.value.save_as(f'{tmp}/embedded_out.png')
        out = cv2.imread(f'{tmp}/embedded_out.png')
        check('埋め込み版からも書き出せる', out is not None and out.shape[:2] == (1080, 1920))
        p2.reload()
        p2.wait_for_timeout(1200)
        check('開き直しても氏名が残る', p2.input_value('#f_name') == '鈴木 一郎', p2.input_value('#f_name'))
        check('開き直しても会社名は既定のまま', p2.input_value('#f_company') == '〇〇法律事務所')

        def embedded_shot(tag):
            with p2.expect_download() as d:
                p2.click('#download')
            path = f'{tmp}/emb_{tag}.png'
            d.value.save_as(path)
            return cv2.imread(path)

        def is_green(im):
            px = im[60, 60]            # 左上は文字もマスコットも無い
            return bool(px[1] > 80 and px[2] < 90)

        im = embedded_shot('first')
        check('チェックを入れなくても背景画像が埋め込まれる', is_green(im),
              f'左上 BGR={tuple(int(v) for v in im[60, 60])}')
        check('マスコットも埋め込まれる',
              int(cv2.inRange(im, np.array([0, 0, 120]), np.array([80, 80, 255])).sum()) > 0)
        check('マスコットの置き場所が引き継がれる',
              p2.get_attribute('#mascotPos button[data-pos="br"]', 'aria-pressed') == 'true')
        p2.reload()
        p2.wait_for_timeout(1500)
        check('2回目に開いても背景画像が残る', is_green(embedded_shot('second')))
        p2.reload()
        p2.wait_for_timeout(1500)
        check('3回目に開いても背景画像が残る', is_green(embedded_shot('third')))

        # --- マスコット画像 ---
        print('[マスコット画像]')
        page.click('#baseClear')
        page.wait_for_timeout(400)

        def mascot_box():
            with page.expect_download() as d:
                page.click('#download')
            path = f'{tmp}/mas.png'
            d.value.save_as(path)
            im = cv2.imread(path)
            red = cv2.inRange(im, np.array([0, 0, 120]), np.array([80, 80, 255]))
            blue = cv2.inRange(im, np.array([120, 0, 0]), np.array([255, 80, 80]))
            ys, xs = np.nonzero(red | blue)
            ry, rx = np.nonzero(red)
            by, bx = np.nonzero(blue)
            return (xs.min(), xs.max(), ys.min(), ys.max(), rx.min() < bx.min())

        for pos, want_left, want_top in [('bl', True, False), ('br', False, False),
                                         ('tl', True, True), ('tr', False, True)]:
            page.click(f'#mascotPos button[data-pos="{pos}"]')
            page.wait_for_timeout(400)
            x0, x1, y0, y1, red_left = mascot_box()
            ok = ((x0 < 960) == want_left) and ((y0 < 540) == want_top)
            check(f'マスコットを{pos}に置ける', ok, f'x={x0}..{x1} y={y0}..{y1}')

        page.click('#mascotPos button[data-pos="bl"]')
        page.wait_for_timeout(300)
        _, _, _, _, red_left_before = mascot_box()
        page.check('#mascotFlip')
        page.wait_for_timeout(400)
        _, _, _, _, red_left_after = mascot_box()
        check('左右反転が効く', red_left_before and not red_left_after,
              f'反転前に赤が左={red_left_before} / 反転後={red_left_after}')
        page.uncheck('#mascotFlip')

        set_range('mascotSize', 50)
        page.wait_for_timeout(400)
        _, _, y0, y1, _ = mascot_box()
        # 画像の塗りは上下半分（400pxのうち y=100..300）なので、指定高さの半分が見える
        check('大きさの指定が効く', abs((y1 - y0) - 0.50 * 1080 * 0.5) < 20, f'{y1 - y0}px')
        set_range('mascotSize', 28)
        page.click('#mascotClear')
        page.wait_for_timeout(400)

        # --- 置き場所と配色 ---
        print('[置き場所]')
        page.click('#layouts button[data-layout="A"]')
        page.click('#baseClear')
        page.click('#logoClear')     # キャッチコピーだけが描かれる状態にして位置を測る
        page.uncheck('#gradient')
        set_range('dim', 0)
        for f in ('f_company', 'f_qual', 'f_name', 'f_namesub', 'f_title', 'f_contact', 'f_qr'):
            page.fill('#' + f, '')
        page.fill('#f_catch', 'ここが一番下に来ます')
        page.select_option('#blockSel', 'catch')
        page.wait_for_timeout(600)

        BG = np.array([0x3f, 0x26, 0x12])      # 既定の背景色 #12263f（BGR）

        def drawn_box(tag):
            with page.expect_download() as d:
                page.click('#download')
            path = f'{tmp}/place_{tag}.png'
            d.value.save_as(path)
            im = cv2.imread(path)
            m = (np.abs(im.astype(int) - BG).sum(axis=2) > 40)
            ys = np.nonzero(m.any(axis=1))[0]
            xs = np.nonzero(m.any(axis=0))[0]
            return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())

        _, _, _, y1 = drawn_box('default')
        check('キャッチコピーの既定は画面上部', y1 < 400, f'下端 y={y1}')
        page.click('#placeGrid button[data-place="bc"]')
        page.wait_for_timeout(600)
        _, _, _, y1 = drawn_box('bottom')
        check('「下」を選ぶと下端近くまで下がる', y1 > 1000, f'下端 y={y1}')
        check('下げても画像からはみ出さない', y1 <= 1079, f'下端 y={y1}')
        page.click('#placeGrid button[data-place="br"]')
        page.wait_for_timeout(600)
        x0, _, _, _ = drawn_box('bottomright')
        check('「右下」を選ぶと右に寄る', x0 > 900, f'左端 x={x0}')
        page.click('#placeDefault')
        page.wait_for_timeout(600)
        _, _, _, y1 = drawn_box('reverted')
        check('「レイアウトの既定位置に戻す」で元に戻る', y1 < 400, f'下端 y={y1}')

        print('[配色]')
        page.set_input_files('#baseFile', f'{tmp}/green.png')
        page.wait_for_timeout(800)
        set_color('overlayColor', '#ff0000')
        set_range('dim', 70)
        page.wait_for_timeout(700)
        with page.expect_download() as d:
            page.click('#download')
        d.value.save_as(f'{tmp}/overlay.png')
        px = cv2.imread(f'{tmp}/overlay.png')[40, 40]
        check('背景画像の上に好きな色を重ねられる', px[2] > 150 and px[1] < 80,
              f'左上 BGR={tuple(int(v) for v in px)}')
        set_range('dim', 0)
        page.fill('#f_name', '山田 太郎')
        set_color('panelColor', '#ff00ff')
        set_range('panelOpacity', 100)
        page.wait_for_timeout(800)
        with page.expect_download() as d:
            page.click('#download')
        d.value.save_as(f'{tmp}/panel.png')
        mag = cv2.inRange(cv2.imread(f'{tmp}/panel.png'),
                          np.array([200, 0, 200]), np.array([255, 60, 255]))
        check('パネル・帯の色を変えられる', int(mag.sum()) > 0)
        page.click('#themes button[data-theme="light"]')
        page.wait_for_timeout(600)
        check('ライトのプリセットが効く',
              page.input_value('#textColor').lower() == '#16202b'
              and page.input_value('#panelColor').lower() == '#ffffff',
              f"{page.input_value('#textColor')} / {page.input_value('#panelColor')}")
        page.click('#themes button[data-theme="brand"]')
        page.wait_for_timeout(600)
        check('ブランド色のプリセットでアクセント色が重なる',
              page.input_value('#overlayColor').lower() == page.input_value('#accentColor').lower())
        page.click('#themes button[data-theme="dark"]')
        page.wait_for_timeout(600)

        print('[選択中ブロックの表示]')
        page.select_option('#blockSel', 'main')
        page.wait_for_timeout(600)
        with page.expect_download() as d:
            page.click('#download')
        d.value.save_as(f'{tmp}/nohl.png')
        hl = cv2.inRange(cv2.imread(f'{tmp}/nohl.png'),
                         np.array([230, 140, 50]), np.array([255, 190, 110]))  # #4da3ff を BGR で
        check('書き出した画像に点線は入らない', int(hl.sum()) == 0)
        n = page.evaluate("""() => {
            const c = document.getElementById('preview');
            const x = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            let n = 0;
            for (let i = 0; i < x.length; i += 4) {
              if (Math.abs(x[i] - 0x4d) < 30 && Math.abs(x[i+1] - 0xa3) < 30 && Math.abs(x[i+2] - 0xff) < 30) n++;
            }
            return n;
        }""")
        check('プレビューには点線が出る', n > 200, f'該当画素 {n}')
        page.click('#baseClear')
        page.wait_for_timeout(300)

        # --- 会社名の複数行表示 ---
        print('[会社名の複数行]')
        page.set_input_files('#baseFile', f'{tmp}/ar_16x9.png')
        page.wait_for_timeout(400)
        page.click('#baseClear')
        page.uncheck('#gradient')
        set_range('dim', 0)
        for f in ('f_qual', 'f_name', 'f_namesub', 'f_title', 'f_contact', 'f_catch', 'f_qr'):
            page.fill('#' + f, '')
        page.click('#layouts button[data-layout="A"]')

        def text_height(value):
            """単色背景の上に描かれた部分の高さを測る"""
            page.fill('#f_company', value)
            page.wait_for_timeout(500)
            with page.expect_download() as d:
                page.click('#download')
            path = f'{tmp}/co_{abs(hash(value))}.png'
            d.value.save_as(path)
            im = cv2.imread(path)
            base = np.array([0x3f, 0x26, 0x12])   # 既定の背景色 #12263f を BGR で
            ys = np.nonzero((np.abs(im.astype(int) - base).sum(axis=2) > 18).any(axis=1))[0]
            return (ys.max() - ys.min()) if len(ys) else 0

        h1 = text_height('〇〇法律グループ')
        h2 = text_height('〇〇法律グループ\n弁護士法人〇〇法律事務所')
        h4 = text_height('Aグループ\nB法律事務所\nC社会保険労務士法人\nD税理士法人')
        h6 = text_height('1\n2\n3\n4\n5\n6')
        line = 0.030 * 1080 * 1.3            # 1行の高さ（文字サイズ 3.0% × 行送り 1.3）
        check('2行にすると1行ぶん高くなる', abs((h2 - h1) - line) < line * 0.3, f'+{h2 - h1}px（1行={line:.0f}px）')
        check('4行にすると3行ぶん高くなる', abs((h4 - h1) - line * 3) < line * 0.5, f'+{h4 - h1}px')
        check('5行目以降は表示しない', h6 == h4, f'6行={h6}px / 4行={h4}px')
        check('5行以上入れると注意書きが出る', '先頭4行' in page.text_content('#companyHint'),
              page.text_content('#companyHint'))

        # --- 配布用 index.html に埋め込まれた既定テンプレート ---
        tpl = embedded_default()
        if tpl is None:
            print('[配布用の既定テンプレート] 埋め込みなし（確認を省略）')
        else:
            print('[配布用の既定テンプレート]')
            p3 = browser.new_context(viewport={'width': 1500, 'height': 1200}).new_page()
            p3.on('console', lambda m: errors.append(f'default console.{m.type}: {m.text}') if m.type == 'error' else None)
            p3.on('pageerror', lambda e: errors.append(f'default pageerror: {e}'))
            p3.goto('file://' + SRC)
            p3.wait_for_timeout(1500)
            check('埋め込まれた会社名で開く',
                  p3.input_value('#f_company') == tpl['text'].get('company', ''),
                  repr(p3.input_value('#f_company')[:40]))
            check('個人情報は埋め込まれていない',
                  not any(tpl['text'].get(k) for k in ('name', 'namesub', 'title', 'qual', 'contact', 'qr')))
            with p3.expect_download() as d:
                p3.click('#download')
            d.value.save_as(f'{tmp}/default.png')
            im = cv2.imread(f'{tmp}/default.png')
            check('そのまま背景を書き出せる', im is not None and im.shape[:2] == (1080, 1920))

        browser.close()

    check('JavaScript のエラーが出ない', not errors, '; '.join(errors[:3]))
    print(f'\n{"失敗 " + str(len(failures)) + " 件" if failures else "すべて成功"}')
    return 1 if failures else 0

if __name__ == '__main__':
    sys.exit(main())
