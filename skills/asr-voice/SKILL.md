---
name: asr-voice
description: 离线语音转文字与语音输入：把会议录音、采访、视频音轨转成文本 / SRT 字幕 / JSON，用麦克风连续听写，或把识别结果写入剪贴板并自动粘贴。SenseVoiceSmall 在本机运行，中英粤日韩等多语种自动识别，音频不出本机，适合隐私敏感的会议转写、字幕制作和桌面语音输入。触发词：语音转文字、录音转写、听写、字幕、语音输入。
---

# 语音转文字（asr-voice）

`office-kit asr` 把音频变文字：单文件转写、SRT 字幕、麦克风连续听写、语音输入到剪贴板。
识别引擎是 **SenseVoiceSmall（llama.cpp + GGUF，CPU，aarch64）**，**离线、无需联网、无需
Python 第三方包**。

## 何时使用

- 会议 / 采访 / 课程录音转文字，整理纪要；
- 给视频、播客生成 SRT 字幕；
- 桌面「按住说话」式语音输入：识别后写剪贴板并尝试自动粘贴；
- 需要隐私：音频、文本、剪贴板都只在本机处理；
- 中英混合、粤语、日语、韩语等 SenseVoice 支持语言的自动识别。

## 不适用

- 需要**强制语言**或行业热词（引擎自动检测语言，不接受热词表）；
- 需要**说话人分离**（谁说了哪句）、时间轴精确到词级（当前是整段或整句级）；
- 要求亚秒级流式字幕（每句识别需要模型推理时间，见「延迟与准确率」）；
- 音乐、强噪声、多人同时说话等场景，准确率会明显下降；
- 超长音频（数小时）请先切段，引擎会整段载入内存。

> 本模块**没有**引入 CT-Transformer 标点模型（约 285 MB）：SenseVoice 自带标点，直接输出；
> 不做额外的简体转换，原文保持模型输出。

## 前置检查

```sh
office-kit --version
office-kit asr --help
office-kit asr models          # 引擎/模型路径、大小、sha256、线程数、可用工具
office-kit asr devices         # 有麦克风时才需要
```

`asr models` 显示「可用」且退出码 0 才继续；缺模型/引擎时退出码 3，先修运行时。
`asr devices` 输出为空不影响 `asr file`，只影响 `mic` / `listen` / `input`。

## 常用命令

### 1. 单文件转文本（自动处理 mp3/m4a/flac/ogg/wav/视频音轨）

```sh
office-kit asr file --input 会议.wav
```

识别结果直接打印到 stdout，适合再接管道：

```sh
office-kit asr file --input 采访.m4a | tee 采访.txt
```

### 2. 生成 SRT 字幕

```sh
office-kit asr file --input 课程.mp4 --format srt > 课程.srt
```

当前上游引擎对整段音频输出一条字幕（`00:00:00,000 --> 音频结尾`）。需要按句切分时，先用
`listen --input`（见第 5 条）得到逐句时间轴，或直接使用引擎输出的整段 SRT。

### 3. JSON 输出（脚本/模型解析）

```sh
office-kit asr file --input 会议.wav --format json
```

```json
{"input":"/abs/会议.wav","duration":3.56,"duration_ms":3560,
 "text":"Hello, this is an offline speech recognition test.",
 "segments":[{"start":0.0,"end":3.56,"text":"..."}],
 "engine":"sensevoice-small-q8","elapsed_ms":1383,"language":"en"}
```

`--json` 与 `--format json` 等价；`--format srt --json` 会额外输出 `format` 和 `srt` 字段。

### 4. 麦克风录 N 秒再识别（**需麦克风**）

```sh
office-kit asr mic --seconds 5
office-kit asr mic --seconds 5 --format json
```

录到静音时输出空文本并在 stderr 提示，退出码仍为 0。

### 5. 连续听写：一行一句（**需麦克风**）

```sh
office-kit asr listen
```

说话 → 停顿约 0.6 秒自动断句 → 每句识别完立刻打印一行（flush），Ctrl-C 结束。
适合会议实时记录、边听边记：

```sh
office-kit asr listen | tee 会议记录.txt
office-kit asr listen --json                # 每行一个 JSON，含 index/start/end/elapsed_ms
office-kit asr listen --once                # 只识别一句就退出
```

不用麦克风也可以验证切句逻辑（把音频文件当麦克风）：

```sh
office-kit asr listen --input 双人对话.wav --json
```

### 6. 语音输入到剪贴板（**需麦克风 + 剪贴板工具**）

```sh
office-kit asr input --seconds 6
```

流程：录音 → 识别 → `wl-copy`/`xclip`/`xsel` 写剪贴板 → `ydotool` 或 `xdotool` 模拟 Ctrl+V。
没有剪贴板工具时会打印文本并提示手动复制，退出码 0。以下情况可只写剪贴板：

```sh
office-kit asr input --seconds 8 --no-paste
```

### 7. 指定 ALSA 采集设备

```sh
office-kit asr devices --json
# [{"card":1,"device":0,"name":"ALC269VC Analog"}]
office-kit asr mic --seconds 5 --device plughw:1,0
office-kit asr listen --device 1,0 --silence 0.8
```

`--device 1,0` 会自动补成 `plughw:1,0`。

### 8. 批量转写目录（shell 循环）

```sh
mkdir -p 转写
for f in 录音/*.wav; do
  [ -e "$f" ] || continue
  base="$(basename "$f" .wav)"
  office-kit asr file --input "$f" --format srt > "转写/${base}.srt"
done
```

批量得到纯文本：

```sh
for f in 录音/*; do
  office-kit asr file --input "$f" >> 全部文本.txt
done
```

注意路径加引号，中文/空格路径可用（`--input "会议 录音.wav"`）。

### 9. 长音频切段后逐段识别

引擎每次都会加载模型并整段处理音频；很长的录音先切成 5–15 分钟：

```sh
mkdir -p 分段 转写
ffmpeg -hide_banner -loglevel error -y -i 长会议.m4a -f segment -segment_time 600 \
  -ac 1 -ar 16000 -c:a pcm_s16le 分段/part-%03d.wav
for f in 分段/part-*.wav; do
  base="$(basename "$f" .wav)"
  office-kit asr file --input "$f" --format srt > "转写/${base}.srt"
done
```

### 10. 校验语言（仅提示，不强制）

```sh
office-kit asr file --input 中文会议.wav --language zh
```

SenseVoice 自动检测语言，`--language` 只会在检测结果不一致时于 stderr 提示；不会改变识别。

## 输出解读

### `file` JSON

| 字段 | 含义 |
| --- | --- |
| `input` | 输入音频绝对路径 |
| `duration` / `duration_ms` | 音频时长（秒 / 毫秒） |
| `text` | 整段文本 |
| `segments[]` | 字幕片段：`start`、`end`（秒）、`text`；整段模式只有一条 |
| `engine` | 固定 `sensevoice-small-q8` |
| `elapsed_ms` | 本次识别耗时（含模型加载） |
| `language` | 检测到的语言码（`zh`/`en`/`yue`/`ja`/`ko`…），未知时 `auto` |
| `format` / `srt` | 仅 `--format srt --json`：SRT 文本 |

### `listen --json`（每行一个）

| 字段 | 含义 |
| --- | --- |
| `index` | 第几句（从 1 开始） |
| `text` | 该句文本 |
| `start` / `end` | 相对监听开始的秒数 |
| `duration` | 该句秒数 |
| `language` | 该句检测语言 |
| `elapsed_ms` | 该句识别耗时 |

### `mic --format json`

`device`、`seconds`（请求录音秒数）、`duration`、`text`、`language`、`speech`（是否检测到
语音）、`engine`、`elapsed_ms`。

### `input --json`

`text`、`language`、`device`、`seconds`、`duration`、`speech`、`clipboard`（工具名或
`null`）、`pasted`（是否成功模拟粘贴）、`engine`、`elapsed_ms`。

### `devices --json`

顶层数组：`[{"card":1,"device":0,"name":"ALC269VC Analog"}]`。

### `models --json`

`available`、`model_size`、`model_sha256_12`、`engine_build`、`threads`、
`tools.ffmpeg/arecord/clipboard/paste`、`devices`。缺依赖时退出码 3。

### 退出码

`0` 成功；`1` 运行时错误（文件损坏、识别失败/超时）；`2` 参数错误；`3` 缺依赖（引擎/模型/
ffmpeg/录音工具）。脚本里优先检查退出码，再解析 JSON。

## 延迟与准确率

- **延迟**：SenseVoiceSmall 是非自回归模型，8 核 aarch64 上 3.56 秒英文音频实测识别约
  1.3–2.5 秒（每次调用都重新加载约 242 MiB 模型，冷启动会多 1–2 秒）。`listen` 每句识别
  完才输出，因此句间停顿后约 1–3 秒出字；系统繁忙时会变长。长音频按整段处理，时间大致随
  时长线性增长。
- **采样率**：统一转成 16 kHz 单声道；重采样由 ffmpeg 完成，比模型直接吃 44.1 kHz 更稳。
- **准确率**：清晰的中文/英文日常语音较好，SenseVoice 自带标点与数字格式化（`withitn`）。
  专业术语、人名、口音、远场/混响、背景音乐与多人重叠会明显下降；专有名词可在识别后用
  LLM/规则做后处理。
- **VAD**：默认能量阈值 0.02（归一化 RMS）+ 过零率门限。安静麦克风可
  `--vad-threshold 0.008`；环境噪声大可提高到 0.05，避免噪声触发幻觉句。
- **断句**：默认静音 0.6 秒断句，`--silence 0.3` 更灵敏（可能切碎），`--silence 1.2`
  更适合慢速讲话。单句上限 15 秒。
- **标点**：模型直接输出，不再叠加外部标点模型。

## 常见错误

| 现象 / 消息 | 原因与处理 |
| --- | --- |
| `未找到 SenseVoice 模型` / `未找到 SenseVoice 识别引擎`（退出码 3） | 运行时缺文件：确认 `runtime/models/llama/llama-funasr-sensevoice` 与 `runtime/models/sensevoice/sensevoice-small-q8.gguf` 存在，引擎需 `chmod +x`。先跑 `office-kit asr models` |
| `未找到录音工具 arecord / ffmpeg`（退出码 3） | 安装 alsa-utils 或 ffmpeg；只是转写文件则不需要麦克风工具 |
| `音频转码失败` / `输入音频不是 16 kHz 单声道 16 位 WAV，且系统中没有 ffmpeg` | 输入损坏、无音轨，或非 WAV 且缺 ffmpeg；安装 ffmpeg，或先转成 16k/mono/s16le WAV（纯 WAV 无 ffmpeg 时会走 Python 后备） |
| `输入文件不存在`（退出码 1） | 路径写错/漏引号；中文和空格路径必须加引号 |
| `未检测到有效语音（静音或麦克风增益过低）` | 麦克风静音、选错设备或增益太低：`asr devices` 后 `--device plughw:<card>,<device>`，或降低 `--vad-threshold` |
| `麦克风采集失败` | 设备被占用/不存在；换 `--device`，或关掉占用程序 |
| `识别引擎失败` / `语音识别超时` | 模型损坏或音频过长；`asr models` 校验 sha256，长音频先切段 |
| `未找到可用的剪贴板工具` | 装 wl-clipboard（Wayland）或 xclip（X11）；此时文本仍会打印 |
| `自动粘贴失败` | ydotool 需要后台守护进程与权限，xdotool 需要 X11 `DISPLAY`；可手动 Ctrl+V |
| `listen` 一直无输出 | 默认设备没有声音或被静音；`asr devices`、`--device`、检查系统输入音量 |
| 识别出「我。」等无关短句 | 噪声/静音被 VAD 当语音；提高 `--vad-threshold`，或先降噪 |
| 长音频内存/耗时 | 引擎整段载入：用 ffmpeg 按 5–15 分钟切段（见第 9 条） |

## 隐私与离线

- **音频不出本机**：识别、VAD、剪贴板、自动粘贴全部在本机完成；模块不发起任何网络请求，
  也不依赖在线 ASR API。可在 `http_proxy=http://127.0.0.1:9` 下正常使用（`test.sh` 已验证）。
- **临时文件**：归一化 WAV、录音、逐句 WAV 都在 `$OFFICE_KIT_CACHE/asr/`，识别后删除；
  异常退出可能残留，可 `rm -rf "$OFFICE_KIT_CACHE/asr"`。
- **剪贴板**：识别文本会进入系统剪贴板，其他本地程序可能读取；敏感内容用完后自行清空。
- **自动粘贴**：`ydotool` / `xdotool` 模拟键盘事件，只在你主动执行 `asr input` 时发生；
  不想自动输入时加 `--no-paste`。
- **许可**：SenseVoiceSmall 权重适用 FunASR Model Open Source License 1.1（保留来源与模型名），
  引擎/运行时代码 MIT；详见同目录 `LICENSES.md`。

## 命令入口（离线机必读）

本技能假设 `office-kit` 已在 `PATH` 中。若执行时报 `command not found`，改用 AppImage 绝对路径：

```sh
KIT="${OFFICE_KIT_BIN:-$HOME/apps/office-kit.AppImage}"
"$KIT" --version
```

后文所有 `office-kit <分组> ...` 都可以等价替换为 `"$KIT" <分组> ...`。
AppImage 需要 `chmod +x`；若提示 FUSE 不可用，加环境变量 `APPIMAGE_EXTRACT_AND_RUN=1`。
