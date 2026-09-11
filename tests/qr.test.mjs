/**
 * QRエンコーダーの検証テスト
 *
 * index.html に埋め込まれた QR エンコーダーを取り出して検証する。
 * （単一 HTML ファイルで配布する方針のため、実装の写しを別に持たない）
 *
 *   実行: node tests/qr.test.mjs
 *
 * 期待値の出どころ:
 *   1. 回帰用の行列 … Python の segno（符号語レベルで一致を確認）および
 *      OpenCV の QRCodeDetector（実際に読み取れることを確認）で検証済みの出力。
 *      検証手順は tests/e2e.py を参照。
 *   2. 最大文字数 … JIS X 0510 のデータ符号語数から算出した値。
 *   3. ブロック構成表 … 行列の幾何（データを置けるモジュール数）から独立に算出し、
 *      「データ符号語数 + 誤り訂正符号語数 = 総符号語数」が成り立つことを確認する。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.join(dir, '..', 'index.html'), 'utf8');
const begin = html.indexOf('// ===== QR-ENCODER-BEGIN =====');
const end = html.indexOf('// ===== QR-ENCODER-END =====');
if (begin < 0 || end < 0) { console.error('index.html に QR エンコーダーの目印が見つかりません'); process.exit(1); }
const source = html.slice(begin, end);
const QR = eval(source + '; QR');
// 内部関数の検証用（本体の公開範囲は変えずに、テストのときだけ取り出す）
const QRI = eval(source.replace('return { encode };', 'return { encode, buildTemplate, RS, dataCapacity };')
                       .replace('const QR = (', 'const QRI = (') + '; QRI');

const fixtures = JSON.parse(fs.readFileSync(path.join(dir, 'qr-fixtures.json'), 'utf8'));

let pass = 0, fail = 0;
const check = (name, cond, extra) => {
  if (cond) pass++;
  else { fail++; console.error(`  NG  ${name}${extra ? ' — ' + extra : ''}`); }
};

/* 1) 既知の出力と完全一致するか（回帰テスト） */
for (const f of fixtures.cases) {
  const got = QR.encode(f.text, f.level).map(r => r.join(''));
  check(`行列一致 level=${f.level} len=${f.text.length}`,
    got.length === f.rows.length && got.every((r, i) => r === f.rows[i]),
    `size=${got.length} 期待=${f.rows.length}`);
}

/* 2) 型番の選択（容量の境目）
   バイトモードの最大文字数 = データ符号語数 - 2（型番1-9。ヘッダ12ビット分） */
for (const [ver, size, caps] of [
  [1, 21, { L: 17, M: 14, Q: 11, H: 7 }],
  [9, 53, { L: 230, M: 180, Q: 130, H: 98 }],
]) {
  for (const [lv, cap] of Object.entries(caps)) {
    check(`型番${ver}${lv} ちょうど${cap}文字`, QR.encode('a'.repeat(cap), lv).length === size,
      `size=${QR.encode('a'.repeat(cap), lv).length}`);
    check(`型番${ver}${lv} ${cap + 1}文字で繰り上がる`, QR.encode('a'.repeat(cap + 1), lv).length === size + 4,
      `size=${QR.encode('a'.repeat(cap + 1), lv).length}`);
  }
}

/* 3) ブロック構成表の整合性: データを置けるモジュール数から総符号語数を算出して突き合わせる */
{
  const ORDER = { L: 0, M: 1, Q: 2, H: 3 };
  let ok = true;
  for (let v = 1; v <= 15; v++) {
    const { size, fixed } = QRI.buildTemplate(v);
    let free = 0;
    for (let r = 0; r < size; r++) for (let c = 0; c < size; c++) if (!fixed[r][c]) free++;
    const total = Math.floor(free / 8);
    for (const lv of Object.keys(ORDER)) {
      const [ecLen, groups] = QRI.RS[v][ORDER[lv]];
      const blocks = groups.reduce((s, [n]) => s + n, 0);
      if (QRI.dataCapacity(v, lv) + ecLen * blocks !== total) {
        ok = false;
        console.error(`  NG  型番${v}-${lv}: ${QRI.dataCapacity(v, lv)}+${ecLen * blocks} ≠ ${total}`);
      }
    }
  }
  check('ブロック構成表と行列の幾何が整合する（型番1-15 × 4レベル）', ok);
}

/* 4) 機能パターンの構造 */
{
  const m = QR.encode('https://example.com/', 'M');
  const n = m.length;
  let ok = true;
  for (const [br, bc] of [[0, 0], [0, n - 7], [n - 7, 0]]) {
    for (let r = 0; r < 7; r++) for (let c = 0; c < 7; c++) {
      const on = (r === 0 || r === 6 || c === 0 || c === 6) || (r >= 2 && r <= 4 && c >= 2 && c <= 4);
      if (m[br + r][bc + c] !== (on ? 1 : 0)) ok = false;
    }
  }
  check('探索パターン', ok);
  let t = true;
  for (let i = 8; i < n - 8; i++) {
    if (m[6][i] !== (i % 2 === 0 ? 1 : 0)) t = false;
    if (m[i][6] !== (i % 2 === 0 ? 1 : 0)) t = false;
  }
  check('タイミングパターン', t);
  check('固定の暗モジュール', m[n - 8][8] === 1);
}

/* 5) 位置合わせパターン（型番7以上でタイミングパターン上にも置かれること） */
{
  const m = QR.encode('a'.repeat(140), 'L');   // 型番7（45×45）
  check('型番7が選ばれる', m.length === 45, `size=${m.length}`);
  // 中心(6,22) の位置合わせパターン: 中心は暗、その上下左右は明
  check('タイミングパターン上の位置合わせパターン',
    m[6][22] === 1 && m[5][22] === 0 && m[7][22] === 0 && m[6][21] === 0 && m[6][23] === 0);
}

/* 6) 容量を超えたらエラーにする */
{
  let threw = false;
  try { QR.encode('x'.repeat(3000), 'H'); } catch { threw = true; }
  check('容量超過でエラーになる', threw);
}

console.log(`QRエンコーダー: ${pass} 件成功, ${fail} 件失敗`);
process.exit(fail ? 1 : 0);
