/**
 * smoke_test.js — validate.js 纯函数冒烟测试（不依赖数据库）
 *
 * 运行: node src/smoke_test.js
 * 退出码: 0 全部通过；1 存在失败
 */
const assert = require('assert');
const { validateAndMerge } = require('./utils/validate');
const defaultsRaw = require('./default_config.json');

function clone(x) {
  return JSON.parse(JSON.stringify(x));
}

/** 构造一份完整合法的基准配置 */
function baseConfig() {
  const c = clone(defaultsRaw);
  delete c._comment;
  return c;
}

let pass = 0;
let fail = 0;
function check(name, fn) {
  try {
    fn();
    pass++;
    console.log(`  [PASS] ${name}`);
  } catch (e) {
    fail++;
    console.log(`  [FAIL] ${name} -> ${e.message}`);
  }
}

console.log('== validateAndMerge 冒烟测试 ==');

check('默认配置应通过校验，且合并结果与默认一致', () => {
  const r = validateAndMerge(baseConfig());
  assert.strictEqual(r.ok, true, JSON.stringify(r.errors));
  assert.deepStrictEqual(r.merged, baseConfig());
});

check('缺省字段自动用默认值填充', () => {
  const r = validateAndMerge({ evening_start: '20:00' });
  assert.strictEqual(r.ok, true, JSON.stringify(r.errors));
  assert.strictEqual(r.merged.evening_start, '20:00');
  assert.strictEqual(r.merged.evening_end, '22:00'); // 默认填充
  assert.strictEqual(r.merged.idle_text, '课间休息'); // 默认填充
  assert.strictEqual(r.merged.allow_local_edit, true);
  assert.ok(Array.isArray(r.merged.subjects) && r.merged.subjects.length === 4);
});

check('非法 HH:MM（小时越界 25:00）被拒绝', () => {
  const c = baseConfig();
  c.evening_start = '25:00';
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('evening_start')), JSON.stringify(r.errors));
});

check('非法 HH:MM（分钟越界 18:77）被拒绝', () => {
  const c = baseConfig();
  c.evening_end = '18:77';
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
});

check('透明度上限越界（main=1.5）被拒绝', () => {
  const c = baseConfig();
  c.opacity.main = 1.5;
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('opacity.main')), JSON.stringify(r.errors));
});

check('透明度下限越界（ball=0.1）被拒绝', () => {
  const c = baseConfig();
  c.opacity.ball = 0.1;
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
});

check('subjects 超过 10 个被拒绝', () => {
  const c = baseConfig();
  c.subjects = [];
  for (let i = 0; i < 11; i++) c.subjects.push({ name: `科${i}`, start: '18:30', end: '19:20' });
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('10')), JSON.stringify(r.errors));
});

check('科目 start=end 被拒绝', () => {
  const c = baseConfig();
  c.subjects.push({ name: '无效', start: '20:00', end: '20:00' });
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
});

check('科目时间段重叠被拒绝', () => {
  const c = baseConfig();
  c.subjects = [
    { name: '甲', start: '18:30', end: '20:00' },
    { name: '乙', start: '19:00', end: '21:00' }
  ];
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('重叠')), JSON.stringify(r.errors));
});

check('科目超出晚自习范围被拒绝（23:00 不在 18:30-22:00 内）', () => {
  const c = baseConfig();
  c.subjects.push({ name: '深夜', start: '23:00', end: '23:30' });
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
});

check('near_seconds 越界（4000）被拒绝', () => {
  const c = baseConfig();
  c.sound.near_seconds = 4000;
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
});

check('near_seconds 非整数被拒绝', () => {
  const c = baseConfig();
  c.sound.near_seconds = 30.5;
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
});

check('非法音频文件名（路径穿越）被拒绝', () => {
  const c = baseConfig();
  c.sound.near_audio = '../../evil.wav';
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
});

check('未知顶层字段被拒绝', () => {
  const c = baseConfig();
  c.unknown_key = 1;
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('unknown_key')), JSON.stringify(r.errors));
});

check('allow_local_edit 非布尔被拒绝', () => {
  const c = baseConfig();
  c.allow_local_edit = 'yes';
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
});

check('跨天配置（22:00-02:00，含跨午夜科目）通过校验', () => {
  const c = baseConfig();
  c.evening_start = '22:00';
  c.evening_end = '02:00';
  c.subjects = [
    { name: '语文', start: '22:10', end: '23:00' },
    { name: '数学', start: '23:10', end: '01:00' }
  ];
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, true, JSON.stringify(r.errors));
});

check('晚自习 evening_start 等于 evening_end 被拒绝', () => {
  const c = baseConfig();
  c.evening_start = '22:00';
  c.evening_end = '22:00';
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('起止时间相同')), JSON.stringify(r.errors));
});

check('merge 后输出为完整 JSON（含全部必需字段）', () => {
  const r = validateAndMerge({});
  assert.strictEqual(r.ok, true, JSON.stringify(r.errors));
  for (const key of ['evening_start', 'evening_end', 'subjects', 'opacity', 'allow_local_edit', 'idle_text', 'sound']) {
    assert.ok(key in r.merged, `缺少字段: ${key}`);
  }
});

check('非对象输入被拒绝', () => {
  const r = validateAndMerge(null);
  assert.strictEqual(r.ok, false);
  const r2 = validateAndMerge([1, 2, 3]);
  assert.strictEqual(r2.ok, false);
});

console.log('');
console.log(`结果: ${pass} 通过, ${fail} 失败`);
process.exit(fail ? 1 : 0);