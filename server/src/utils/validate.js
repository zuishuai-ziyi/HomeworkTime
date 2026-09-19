/**
 * utils/validate.js — 业务配置轻量校验器（手写实现，不依赖 ajv）
 *
 * 依据 config.schema.json（字段契约）与 default_config.json（默认值）：
 *   - 缺省字段用默认值填充（merge 后输出完整 JSON，便于整行保存）
 *   - 未知字段报错（对应 additionalProperties: false）
 *   - 类型、HH:MM 格式、范围、文件名合法性、科目时间自洽与区间合理性检查
 *
 * 导出 validateAndMerge(config) -> { ok, errors, merged }
 */
const path = require('path');
const fs = require('fs');

const SCHEMA_FILE = path.join(__dirname, '..', 'config.schema.json');
const DEFAULT_FILE = path.join(__dirname, '..', 'default_config.json');

// 加载两份契约文件（启动时读取一次即可）
const schema = JSON.parse(fs.readFileSync(SCHEMA_FILE, 'utf8'));
const defaultsRaw = JSON.parse(fs.readFileSync(DEFAULT_FILE, 'utf8'));

// 剔除 default_config.json 中以 "_" 开头的说明占位键（如 _comment）
const defaults = {};
for (const [k, v] of Object.entries(defaultsRaw)) {
  if (!k.startsWith('_')) defaults[k] = v;
}

/** 深拷贝（配置为纯 JSON 数据，JSON 序列化即可） */
function deepClone(obj) {
  return obj === undefined ? undefined : JSON.parse(JSON.stringify(obj));
}

/** HH:MM 24 小时制正则（与 schema pattern 一致） */
const HHMM_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
/** 音频文件名正则（仅字母数字 _ - . 且 .wav 结尾） */
const WAV_RE = /^[A-Za-z0-9._-]+\.wav$/;

/** "HH:MM" 转当天分钟数 */
function toMinutes(hhmm) {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + m;
}

/**
 * 校验并合并配置
 * @param {object} input 客户端/后台提交的配置对象
 * @returns {{ok: boolean, errors: string[], merged: object|null}}
 *   ok=true 时 merged 为填充完整默认值后的配置；
 *   否则 merged 为 null，errors 为具体原因列表。
 */
function validateAndMerge(input) {
  const errors = [];

  // 基础类型检查
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return { ok: false, errors: ['config 必须是一个 JSON 对象'], merged: null };
  }

  // 以默认配置为底，逐字段校验并合并
  const merged = deepClone(defaults);

  // ---- 1) 未知顶层字段 ----
  for (const key of Object.keys(input)) {
    if (!(key in defaults)) {
      errors.push(`未知配置项: ${key}`);
    }
  }

  // ---- 2) evening_start / evening_end：HH:MM 格式 ----
  const eveningStart = resolveTime(input, 'evening_start', merged, errors);
  const eveningEnd = resolveTime(input, 'evening_end', merged, errors);

  // ---- 2.1) 晚自习起止不允许相同 ----
  // 虽然跨天规则是 end <= start 即视为跨天，但 24h 全开语义无意义且危险
  // （提示音/状态机整日处于晚自习），这里显式拒绝相等值。
  if (eveningStart !== null && eveningEnd !== null && eveningStart === eveningEnd) {
    errors.push('晚自习起止时间相同：结束时间不能等于开始时间');
  }

  // ---- 3) subjects：数组、≤10 个、每项字段与时间自洽、区间合理 ----
  const subjVal = input.subjects;
  let segments = []; // 用于重叠/越界检查
  if (subjVal === undefined) {
    // 使用默认 subjects
  } else if (!Array.isArray(subjVal)) {
    errors.push('配置项 subjects 必须为数组');
  } else if (subjVal.length > 10) {
    errors.push(`subjects 最多 10 个科目，当前 ${subjVal.length} 个`);
  } else {
    let subjValid = true;
    let validated = [];
    subjVal.forEach((item, idx) => {
      const pos = `subjects[${idx}]`;
      if (!item || typeof item !== 'object' || Array.isArray(item)) {
        errors.push(`${pos} 必须是对象`);
        subjValid = false;
        return;
      }
      // 每项不允许多余字段
      for (const k of Object.keys(item)) {
        if (!['name', 'start', 'end'].includes(k)) {
          errors.push(`${pos} 存在未知字段: ${k}`);
          subjValid = false;
        }
      }
      // name
      if (typeof item.name !== 'string' || item.name.trim().length < 1 || item.name.length > 32) {
        errors.push(`${pos}.name 必须为 1~32 字符的字符串`);
        subjValid = false;
      }
      // start / end：HH:MM
      const startOk = typeof item.start === 'string' && HHMM_RE.test(item.start);
      const endOk = typeof item.end === 'string' && HHMM_RE.test(item.end);
      if (!startOk) errors.push(`${pos}.start 必须为 HH:MM 格式（如 18:30）`);
      if (!endOk) errors.push(`${pos}.end 必须为 HH:MM 格式（如 19:20）`);
      if (startOk && endOk) {
        // 开始时间不能等于结束时间
        if (item.start === item.end) {
          errors.push(`${pos} 开始时间不能等于结束时间`);
          subjValid = false;
        } else {
          segments.push({ start: item.start, end: item.end, pos, name: item.name });
          validated.push({ name: item.name, start: item.start, end: item.end });
        }
      }
    });
    if (subjValid) merged.subjects = deepClone(validated);
  }

  // ---- 4) opacity：main/ball/config 数值范围 0.2~1.0 ----
  const opVal = input.opacity;
  if (opVal === undefined) {
    // 使用默认值
  } else if (!opVal || typeof opVal !== 'object' || Array.isArray(opVal)) {
    errors.push('配置项 opacity 必须为对象');
  } else {
    for (const k of Object.keys(opVal)) {
      if (!['main', 'ball', 'config'].includes(k)) errors.push(`opacity 存在未知字段: ${k}`);
    }
    for (const [k, def] of Object.entries(defaults.opacity)) {
      const v = opVal[k];
      if (v === undefined) {
        merged.opacity[k] = def;
      } else if (typeof v !== 'number' || Number.isNaN(v) || v < 0.2 || v > 1.0) {
        errors.push(`opacity.${k} 必须为 0.2~1.0 之间的数值`);
      } else {
        merged.opacity[k] = v;
      }
    }
  }

  // ---- 5) allow_local_edit：布尔 ----
  if (input.allow_local_edit !== undefined) {
    if (typeof input.allow_local_edit !== 'boolean') {
      errors.push('allow_local_edit 必须为布尔值');
    } else {
      merged.allow_local_edit = input.allow_local_edit;
    }
  }

  // ---- 6) idle_text：1~64 字符字符串 ----
  if (input.idle_text !== undefined) {
    if (typeof input.idle_text !== 'string' || input.idle_text.trim().length < 1 || input.idle_text.length > 64) {
      errors.push('idle_text 必须为 1~64 字符的字符串');
    } else {
      merged.idle_text = input.idle_text;
    }
  }

  // ---- 7) sound：总开关/临近阈值/音频文件名/各自开关 ----
  const sVal = input.sound;
  if (sVal === undefined) {
    // 使用默认值
  } else if (!sVal || typeof sVal !== 'object' || Array.isArray(sVal)) {
    errors.push('配置项 sound 必须为对象');
  } else {
    for (const k of Object.keys(sVal)) {
      if (!['enabled', 'near_seconds', 'near_audio', 'near_enabled', 'end_audio', 'end_enabled'].includes(k)) {
        errors.push(`sound 存在未知字段: ${k}`);
      }
    }
    if (sVal.enabled !== undefined) {
      if (typeof sVal.enabled !== 'boolean') errors.push('sound.enabled 必须为布尔值');
      else merged.sound.enabled = sVal.enabled;
    }
    if (sVal.near_seconds !== undefined) {
      const ns = sVal.near_seconds;
      if (typeof ns !== 'number' || !Number.isInteger(ns) || ns < 1 || ns > 3600) {
        errors.push('sound.near_seconds 必须为 1~3600 的整数（单位秒）');
      } else {
        merged.sound.near_seconds = ns;
      }
    }
    if (sVal.near_audio !== undefined) {
      if (typeof sVal.near_audio !== 'string' || !WAV_RE.test(sVal.near_audio)) {
        errors.push('sound.near_audio 必须为合法的 .wav 文件名（仅含字母数字 _ - .）');
      } else {
        merged.sound.near_audio = sVal.near_audio;
      }
    }
    if (sVal.near_enabled !== undefined) {
      if (typeof sVal.near_enabled !== 'boolean') errors.push('sound.near_enabled 必须为布尔值');
      else merged.sound.near_enabled = sVal.near_enabled;
    }
    if (sVal.end_audio !== undefined) {
      if (typeof sVal.end_audio !== 'string' || !WAV_RE.test(sVal.end_audio)) {
        errors.push('sound.end_audio 必须为合法的 .wav 文件名（仅含字母数字 _ - .）');
      } else {
        merged.sound.end_audio = sVal.end_audio;
      }
    }
    if (sVal.end_enabled !== undefined) {
      if (typeof sVal.end_enabled !== 'boolean') errors.push('sound.end_enabled 必须为布尔值');
      else merged.sound.end_enabled = sVal.end_enabled;
    }
  }

  // ---- 8) 科目区间合理性 ----
  // "不要求覆盖"晚自习全部区间，但科目段应落在晚自习起止范围内，且互不重叠
  if (eveningStart !== null && eveningEnd !== null && segments.length > 0) {
    const esm = toMinutes(eveningStart);
    const eem = toMinutes(eveningEnd);
    const crossMidnight = esm >= eem; // end <= start 视为跨天
    const inEveningRange = (m) => (crossMidnight ? m >= esm || m <= eem : m >= esm && m <= eem);

    // 8.1 越界检查
    for (const seg of segments) {
      const sm = toMinutes(seg.start);
      const em = toMinutes(seg.end);
      if (!inEveningRange(sm) || !inEveningRange(em)) {
        errors.push(`${seg.pos} "(${seg.name})" 时间段 ${seg.start}-${seg.end} 超出晚自习范围 ${eveningStart}-${eveningEnd}`);
      }
    }
    // 8.2 重叠检查（区间 [s, e) 前闭后开）
    for (let i = 0; i < segments.length; i++) {
      for (let j = i + 1; j < segments.length; j++) {
        const a = segments[i];
        const b = segments[j];
        const as = toMinutes(a.start);
        const ae = toMinutes(a.end);
        const bs = toMinutes(b.start);
        const be = toMinutes(b.end);
        if (as < be && bs < ae) {
          errors.push(`科目时间段重叠: "${a.name}" ${a.start}-${a.end} 与 "${b.name}" ${b.start}-${b.end}`);
        }
      }
    }
  }

  return errors.length
    ? { ok: false, errors, merged: null }
    : { ok: true, errors: [], merged };
}

/**
 * 校验某个 HH:MM 字段；合法则写入 merged，非法则记错误
 * @returns {string|null} 合并且校验通过后的时间字符串
 */
function resolveTime(input, key, merged, errors) {
  const val = input[key];
  if (val === undefined) return merged[key]; // 缺省用默认值
  if (typeof val === 'string' && HHMM_RE.test(val)) {
    merged[key] = val;
    return val;
  }
  errors.push(`配置项 ${key} 必须为 HH:MM 格式（24 小时制，如 18:30）`);
  return null; // 该字段校验失败，后续区间检查自动跳过
}

module.exports = {
  validateAndMerge,
  schema,
  defaults
};