# asr — 离线语音识别 / 连续听写 / 语音输入

`asr` 是 office-kit 的语音模块：用 **SenseVoiceSmall（llama.cpp，CPU，aarch64）** 在本机把
音频转成文本、SRT 字幕或 JSON，并提供麦克风连续听写与「识别 → 剪贴板 → 自动粘贴」的
语音输入能力。**运行期完全离线，不需要 Python 第三方包。**

## 快速开始

```sh
office-kit asr models                       # 先确认引擎/模型就绪
office-kit asr file --input 会议.wav         # 整段转文本
office-kit asr file --input 会议.mp4 --format srt > 会议.srt
office-kit asr listen                       # 连续听写，一行一句，Ctrl-C 结束（需麦克风）
office-kit asr input --seconds 6            # 语音输入到剪贴板（需麦克风）
```

模块入口也可单独执行：

```sh
./modules/asr/bin/asr file --input 录音.m4a --json
```

## 目录

```
modules/asr/
  bin/asr                # bash 包装：定位根目录/运行时，exec 到 $OFFICE_KIT_PY
  lib/asr_cli.py         # 全部逻辑（Python 3 标准库，无第三方依赖）
  test.sh                # 自检脚本，成功打印 OK asr
  README.md
```

`lib/` 下没有第三方 wheel：音频解码/重采样用系统 `ffmpeg`，WAV/录音/VAD/JSON 全部用
CPython 标准库完成。

## 子命令

### `asr file --input F [--format text|srt|json] [--json] [--language auto|zh|en]`

任意输入格式（mp3 / m4a / flac / ogg / wav / 视频容器里的音轨）：先用 ffmpeg 归一化为
**16000 Hz、单声道、s16le WAV**（放在 `$OFFICE_KIT_CACHE/asr/`，识别后删除），再调用引擎。
如果输入已经是 16 kHz 单声道 16 位 WAV，则直接使用，不重复转码。

- `--format text`（默认）：只输出文本，一行。
- `--format srt`：调用引擎 `--srt`；当前上游引擎对整段音频输出**一条**字幕，时间轴为
  `00:00:00,000 --> 音频时长`。若引擎没有给出合法 SRT，则按整段单条 SRT 兜底。
- `--format json` / `--json`：输出单个 JSON 对象（UTF-8 不转义中文）。
- `--language zh|en`：SenseVoice 会自动检测语言，**不能强制**；该参数只用于对检测结果做
  提示（不一致时在 stderr 提示）。`auto` 为默认。
- 输入音频是纯数字静音时直接返回空文本，不调用引擎，避免模型幻觉出「我。」之类的文本。
- 视频文件取第一条音轨（ffmpeg 默认行为）。

JSON 字段：

```json
{
  "input": "/abs/path/会议.wav",
  "duration": 3.56,
  "duration_ms": 3560,
  "text": "Hello, this is an offline speech recognition test.",
  "segments": [{"start": 0.0, "end": 3.56, "text": "..."}],
  "engine": "sensevoice-small-q8",
  "elapsed_ms": 1383,
  "language": "en"
}
```

`--format srt --json` 额外给出 `"format": "srt"` 和 `"srt": "1\n00:00:00,000 --> ..."`。

### `asr mic [--seconds N] [--format text|json] [--json] [--device D]`

用 `arecord -f S16_LE -r 16000 -c 1 -t wav` 录 N 秒（默认 5 秒；没有 arecord 时回退
`ffmpeg -f alsa`），先做能量 VAD 检查；确认有语音后才调用引擎。静音时输出空文本、stderr
提示，退出码仍为 0。`--device` 支持 `plughw:1,0` 或简写 `1,0`。

### `asr listen [--device D] [--once] [--json] [--vad-threshold 0.02] [--silence 0.6]`

连续听写：后台线程持续读取声卡原始 PCM（100 ms 一块、30 ms 一帧），用**能量 + 过零率**
VAD 切句；句间静音超过 `--silence` 秒即判定一句结束，逐句送引擎识别，**stdout 一行一句并
flush**，诊断信息写 stderr。Ctrl-C 优雅退出（退出码 0），并终止录音子进程。

- `--once`：识别一句就退出。
- `--json`：每行一个 JSON 对象：`index / text / start / end / duration / language / elapsed_ms`。
- `--vad-threshold`：归一化 RMS 能量阈值，默认 0.02；安静麦克风可降到 0.008，噪声大可升到 0.05。
- `--silence`：断句静音秒数，默认 0.6。
- 单句最长 15 秒，超过强制切分，避免长句占用内存/延迟过大。
- 少于 200 ms 的语音碎片会被丢弃；句首保留 300 ms 预卷。
- `--input F`：用音频文件模拟麦克风（调试/测试用，不占声卡），同一套 VAD 与输出格式。

### `asr input [--device D] [--seconds 6] [--json] [--no-paste]`

语音输入：录音 → 识别 → 写剪贴板 → 尝试自动粘贴。

- 剪贴板：Wayland 优先 `wl-copy`，X11 优先 `xclip`，其次 `xsel`。
- 自动粘贴：`ydotool key 29:1 47:1 47:0 29:0`（模拟 Ctrl+V），否则 `xdotool key --clearmodifiers ctrl+v`。
- 两个工具都没有时，**打印识别文本并提示手动粘贴，退出码 0**；识别文本始终写 stdout
  （`--json` 时以 JSON 输出），便于脚本使用。
- `--no-paste`：只写剪贴板，不模拟按键。
- `--input F`：用音频文件代替麦克风（调试/测试）。

### `asr devices [--json]`

解析 `arecord -l` 列出 ALSA 采集设备；没有 arecord 时回退解析 `/proc/asound/pcm` 与
`/proc/asound/cards`。JSON 是**顶层数组**：

```json
[{"card": 1, "device": 0, "name": "ALC269VC Analog"}]
```

### `asr models [--json]`

报告引擎/模型是否存在、路径、大小、构建日期、`sha256` 前 12 位、线程数、可用工具与采集
设备数。缺引擎或模型时退出码 3。sha256 结果按 `size + mtime` 缓存在
`$OFFICE_KIT_CACHE/asr/sha256-cache.json`，首次约 1.5 秒，之后即时返回。

```json
{
  "engine": "sensevoice-small-q8",
  "available": true,
  "engine_bin": "/…/runtime/models/llama/llama-funasr-sensevoice",
  "engine_size": 3837824,
  "engine_version": "llama-funasr-sensevoice（bundled）",
  "engine_build": "2026-10-25",
  "engine_sha256_12": "877e3e58d044",
  "model": "/…/runtime/models/sensevoice/sensevoice-small-q8.gguf",
  "model_size": 254208320,
  "model_size_human": "242.4 MiB",
  "model_sha256_12": "4ae45c94422d",
  "threads": 5,
  "tools": {"ffmpeg": "/usr/bin/ffmpeg", "arecord": "/usr/bin/arecord",
            "clipboard": null, "paste": "xdotool", "...": "..."},
  "devices": 1
}
```

> 上游 `llama-funasr-sensevoice` 没有 `--version`（传 `--version` 会以退出码 1 打印 usage），
> 因此 `engine_version` 记录为 bundled，另给出二进制构建日期与 sha256 作为版本指纹。

## 实现要点

### 引擎调用

```sh
llama-funasr-sensevoice -m sensevoice-small-q8.gguf -a in.wav \
    --backend cpu [--srt] [--keep-tags]
```

- 引擎**不支持 `-t`/`--threads`**（`--help` 已确认）。线程数通过环境变量 `SV_THREADS`
  （同时设置 `OMP_NUM_THREADS`）传给底层运行时，默认 `min(5, CPU-1)`；
  `OFFICE_KIT_ASR_THREADS` 可覆盖。
- `--keep-tags` 用于读取 `<|zh|>` / `<|en|>` 语言标签，输出前会把 `<|…|>` 标签全部剥离。
- 每次识别都是独立进程（模型逐次加载），进程组隔离；超时按音频时长计算
  `max(60s, 时长×8+40s)`，Ctrl-C 会杀掉整个进程组，不留孤儿进程。
- 运行目录切到缓存目录，音频路径统一转为绝对路径，因此中文/空格路径安全（不使用 `eval`）。

### 音频归一化

- 优先判断输入是否已经是 16 kHz/mono/s16le WAV；是则零拷贝。
- 否则 `ffmpeg -nostdin -hide_banner -loglevel error -y -i IN -vn -ac 1 -ar 16000 -c:a pcm_s16le -f wav OUT`。
- 没有 ffmpeg 时：PCM WAV 用标准库 `wave` + `audioop` 转为 16 kHz 单声道 16 位（线性重采样）；
  非 WAV / 压缩 WAV / 多声道（>2）返回退出码 3，并给出可执行的修复命令。
- 临时文件在 `$OFFICE_KIT_CACHE/asr/`，`finally` 中删除；缓存目录不可写时退到系统临时目录。

### VAD

- 30 ms 帧，计算归一化 RMS 与过零率；`rms >= threshold 且 zcr <= 0.35` 记为语音帧。
- 300 ms 预卷、240 ms 句尾保留、200 ms 最小语音长度、0.6 s 静音断句、15 s 单句上限。
- 采集与识别解耦：采集线程持续读声卡入队，主线程逐句识别，避免识别慢导致 ALSA 丢音；
  队列上限 32 句。
- 纯数字静音文件（全 0 采样）直接判空，不送引擎。

### 缓存与清理

| 路径 | 内容 |
| --- | --- |
| `$OFFICE_KIT_CACHE/asr/norm-*.wav` | ffmpeg 归一化临时文件，识别后删除 |
| `$OFFICE_KIT_CACHE/asr/seg-*.wav` | listen 每句的临时 WAV，识别后删除 |
| `$OFFICE_KIT_CACHE/asr/mic-*.wav` | mic/input 录音临时文件，识别后删除 |
| `$OFFICE_KIT_CACHE/asr/sha256-cache.json` | 模型/引擎校验值缓存 |

异常退出可能留下临时音频，可安全执行 `rm -rf "$OFFICE_KIT_CACHE/asr"`。

## 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 成功（包括 input 没有剪贴板工具、mic 录到静音） |
| 1 | 运行时错误：文件不存在、ffmpeg 转码失败、引擎识别失败/超时 |
| 2 | 参数错误（argparse 自动处理） |
| 3 | 缺依赖：引擎/模型缺失、缺少 ffmpeg（非 WAV 输入）、缺少录音工具 |

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `OFFICE_KIT_PY` | 运行时 Python（默认 `$OFFICE_KIT_RUNTIME/python/bin/python3`） |
| `OFFICE_KIT_MODELS` | 模型根目录（默认 `$OFFICE_KIT_RUNTIME/models`） |
| `OFFICE_KIT_CACHE` | 缓存根目录（默认 `$OFFICE_KIT_DATA/cache`） |
| `OFFICE_KIT_ASR_THREADS` | 覆盖识别线程数（1..CPU） |
| `WAYLAND_DISPLAY` / `DISPLAY` | 决定优先使用 wl-copy 还是 xclip/xsel |
| `http_proxy` 等 | 与本模块无关：运行期不发起任何网络请求 |

## 与 asr-now Lite 的关系

参考 `/home/link/桌面/code/asr-now` 的 Lite 版：相同的 `llama-funasr-sensevoice` 引擎、
SenseVoiceSmall Q8 模型、16 kHz 单声道约定与 `SV_THREADS` 线程设置。本模块重新实现为
单文件 CLI，不启动 HTTP 服务、不依赖浏览器。

**没有引入**的可选能力：CT-Transformer 标点模型（约 285 MB，SenseVoice 已自带标点）、
Qwen3-ASR、说话人分离、热词/强制语言、流式实时字幕。长音频请先切段（见 SKILL.md）。

## 测试

```sh
bash modules/asr/test.sh
```

测试用 `mktemp -d` 创建独立临时目录并在退出时删除，不依赖仓库里的 `.tmp`，可在干净仓库
和任意工作目录重复运行；测试缓存（归一化 WAV / sha256）也指向该临时目录。

测试用 ffmpeg + libflite 合成英文语音（缺失时退化为静音 WAV 只验证流程），覆盖：

- `--help`、退出码 2/1；
- `file` 的 text / json / srt / srt+json 输出与字段断言；
- 44.1 kHz 立体声 mp3 → 16 kHz 单声道归一化、中文/空格路径；
- `models` / `devices` 的 JSON 结构；
- `listen` 的 VAD 切句（两句话切出 ≥2 行）与 `--once`；
- `mic` 无设备/静音时打印 SKIP 不失败；
- 全程 `http_proxy=http://127.0.0.1:9`，验证断网语义。

成功输出 `OK asr`。注意：每次识别都要重新加载模型，测试会跑约 11 次识别（含 listen 的
逐句识别）；8 核 aarch64 上低负载约 30~60 秒，系统繁忙时可能超过 2 分钟。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `asr models` 退出码 3 | 确认 `runtime/models/llama/llama-funasr-sensevoice` 与 `runtime/models/sensevoice/sensevoice-small-q8.gguf` 存在；`chmod +x` 引擎 |
| `devices` 为空 / `mic` 退出码 3 | 检查麦克风、`arecord -l`、是否被占用；仍不行用 `asr file` |
| `listen` 没反应 | 默认设备不对或被静音：`asr devices` 后用 `--device plughw:<card>,<device>`；降低 `--vad-threshold` |
| 识别出无关短句 | 噪声触发 VAD：提高 `--vad-threshold`；或输入本身是静音 |
| 非 WAV 报「未找到 ffmpeg」 | 安装 ffmpeg，或先转成 16k/mono/s16le WAV |
| 长音频很慢/超时 | 引擎整段加载：先用 ffmpeg 按 5–15 分钟切段再逐段识别 |
| 剪贴板没内容 / 不粘贴 | 安装 wl-clipboard（Wayland）或 xclip（X11）；自动粘贴需要 ydotool 守护进程或 xdotool；缺工具时文本仍打印 |
| 中文/空格路径 | 全命令用引号：`--input "会议 录音.wav"` |

## 许可

模型与上游组件许可见 [skills/asr-voice/LICENSES.md](../../skills/asr-voice/LICENSES.md)。
SenseVoiceSmall 模型权重适用 **FunASR Model Open Source License 1.1**（需保留来源与模型名），
llama.cpp / FunASR 运行时代码为 MIT。ffmpeg、alsa-utils、wl-clipboard、xclip、xdotool、
ydotool 是**系统可选工具**，不随 office-kit 分发。
