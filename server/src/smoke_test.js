/**
 * smoke_test.js — 服务端纯函数冒烟测试（不依赖数据库）
 *
 * 覆盖：validateAndMerge（业务配置校验器）+ install_script（一键安装脚本生成器）
 * 运行: node src/smoke_test.js
 * 退出码: 0 全部通过；1 存在失败
 */
const assert = require('assert');
const { validateAndMerge } = require('./utils/validate');
const defaultsRaw = require('./default_config.json');
const {
  normalizeClientBaseUrl,
  normalizeInstallDir,
  isValidSlug,
  isValidSinkSlug,
  parseSinkUrl,
  maskApiKey,
  buildScriptUrl,
  buildInstallCommand,
  buildInstallScript
} = require('./utils/install_script');

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

check('theme 合法色值通过校验并归一化为大写', () => {
  const c = baseConfig();
  c.theme = { card: '#023e8a', accent: '#12ab34', timeline: '#03045E' };
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, true, JSON.stringify(r.errors));
  assert.deepStrictEqual(r.merged.theme, {
    card: '#023E8A', accent: '#12AB34', timeline: '#03045E'
  });
});

check('theme 非法色值（#FFF / red）被拒绝', () => {
  const c = baseConfig();
  c.theme = { card: '#FFF' };
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('theme.card')), JSON.stringify(r.errors));
  const c2 = baseConfig();
  c2.theme = { accent: 'red' };
  const r2 = validateAndMerge(c2);
  assert.strictEqual(r2.ok, false);
});

check('theme 存在未知字段被拒绝', () => {
  const c = baseConfig();
  c.theme = { ...c.theme, junk: '#123456' };
  const r = validateAndMerge(c);
  assert.strictEqual(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('junk')), JSON.stringify(r.errors));
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
  for (const key of ['evening_start', 'evening_end', 'subjects', 'opacity', 'theme', 'allow_local_edit', 'idle_text', 'sound']) {
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
console.log('== install_script 一键安装脚本冒烟测试 ==');

check('normalizeClientBaseUrl：归一化去除末尾斜杠', () => {
  assert.strictEqual(normalizeClientBaseUrl('http://hw.school.xiaoziyi.com:81/'), 'http://hw.school.xiaoziyi.com:81');
  assert.strictEqual(normalizeClientBaseUrl('https://example.com/a/'), 'https://example.com/a');
});

check('normalizeClientBaseUrl：非 http(s)、含空白/引号被拒绝', () => {
  assert.throws(() => normalizeClientBaseUrl('ftp://example.com'), /http/);
  assert.throws(() => normalizeClientBaseUrl('http://exa mple.com'), /非法/);
  assert.throws(() => normalizeClientBaseUrl("http://example.com/'"), /非法/);
  assert.throws(() => normalizeClientBaseUrl(''), /非法/);
});

check('normalizeInstallDir：合法 Windows 路径通过并去除末尾反斜杠', () => {
  assert.strictEqual(normalizeInstallDir('C:\\HomeworkTime'), 'C:\\HomeworkTime');
  assert.throws(() => normalizeInstallDir('C:\\HomeworkTime\\'), /结尾/);
});

check('normalizeInstallDir：相对路径 / 含引号被拒绝', () => {
  assert.throws(() => normalizeInstallDir('HomeworkTime'), /绝对路径/);
  assert.throws(() => normalizeInstallDir("C:\\Ho'me"), /非法/);
  assert.throws(() => normalizeInstallDir('C:\\'), /绝对路径/);
});

check('isValidSlug / isValidSinkSlug 白名单', () => {
  assert.ok(isValidSlug('AbCdEf1234567890'));
  assert.ok(!isValidSlug('short'));
  assert.ok(!isValidSlug('含中文的slug12345'));
  assert.ok(isValidSinkSlug(''));
  assert.ok(isValidSinkSlug('ht-install'));
  assert.ok(!isValidSinkSlug('-abc'));
  assert.ok(!isValidSinkSlug('a b'));
});

check('parseSinkUrl：提取 origin 与 hostname（domain 不含端口）', () => {
  const r = parseSinkUrl('https://s.example.com:8443/');
  assert.strictEqual(r.origin, 'https://s.example.com:8443');
  assert.strictEqual(r.hostname, 's.example.com');
  assert.throws(() => parseSinkUrl('not-a-url'), /非法/);
  assert.throws(() => parseSinkUrl('ftp://s.example.com'), /非法/);
});

check('maskApiKey：脱敏展示（保留前后 4 位，短 Key 整体打码）', () => {
  assert.strictEqual(maskApiKey('sk_abcdefghijklmnop'), 'sk_a***mnop');
  assert.strictEqual(maskApiKey('NUXT_SITE_TOKEN_VALUE'), 'NUXT***ALUE');
  assert.strictEqual(maskApiKey('short'), '****');
  assert.strictEqual(maskApiKey('12345678'), '****');
  assert.strictEqual(maskApiKey(''), '');
  assert.strictEqual(maskApiKey(null), '');
});

check('buildInstallCommand：生成 irm | iex 单行命令', () => {
  const cmd = buildInstallCommand('https://s.example.com/htinstall');
  assert.strictEqual(
    cmd,
    "powershell -NoProfile -ExecutionPolicy Bypass -Command \"irm 'https://s.example.com/htinstall' | iex\""
  );
});

check('buildInstallScript：embedConfig 时包含下载/解压/local_config 关键步骤', () => {
  const s = buildInstallScript({
    slug: 'AbCdEf1234567890',
    clientBaseUrl: 'http://hw.school.xiaoziyi.com:81',
    installDir: 'C:\\HomeworkTime',
    embedConfig: true,
    clientToken: 'tok123'
  });
  assert.ok(s.includes('$PkgUrl = "$Base/api/install/s/$Slug/package"'));
  assert.ok(s.includes("Expand-Archive -Path $Zip -DestinationPath $Dir -Force"));
  assert.ok(s.includes('"server_base_url": "http://hw.school.xiaoziyi.com:81"'));
  assert.ok(s.includes('"client_token": "tok123"'));
  assert.ok(s.includes('"autostart": true'));
  assert.ok(s.includes('[System.IO.File]::WriteAllText'));
  assert.ok(s.includes("Start-Process -FilePath $Exe"));
  assert.ok(!/[\u4e00-\u9fff]/.test(s), '脚本应为纯 ASCII');
  assert.ok(s.endsWith('\r\n'), '脚本应以 CRLF 结尾');
  // here-string 终止符必须位于行首
  assert.ok(/^'@\r$/m.test(s));
});

check('buildInstallScript：embedConfig=false 时不写入 local_config', () => {
  const s = buildInstallScript({
    slug: 'AbCdEf1234567890',
    clientBaseUrl: 'http://hw.school.example.com',
    installDir: 'C:\\HomeworkTime',
    embedConfig: false,
    clientToken: 'tok123'
  });
  assert.ok(!s.includes('client_token'));
  assert.ok(s.includes('first-run guide window'));
});

check('buildInstallScript：注入面收敛 —— 非法安装目录在白名单层被拒绝', () => {
  assert.throws(() => buildInstallScript({
    slug: 'AbCdEf1234567890',
    clientBaseUrl: 'http://hw.example.com',
    installDir: "C:\\It's HT",
    embedConfig: false,
    clientToken: null
  }), /非法/);
});

check('buildInstallScript：非法参数被拒绝', () => {
  assert.throws(() => buildInstallScript({
    slug: 'bad slug',
    clientBaseUrl: 'http://ok.example.com',
    installDir: 'C:\\HomeworkTime',
    embedConfig: true,
    clientToken: ''
  }), /slug/);
  assert.throws(() => buildInstallScript({
    slug: 'AbCdEf1234567890',
    clientBaseUrl: 'java script:alert(1)',
    installDir: 'C:\\HomeworkTime',
    embedConfig: true,
    clientToken: ''
  }), /非法/);
});

console.log('');
console.log(`结果: ${pass} 通过, ${fail} 失败`);
process.exit(fail ? 1 : 0);