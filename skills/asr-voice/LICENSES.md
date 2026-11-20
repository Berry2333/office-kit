# asr-voice 第三方许可与来源

本技能（`skills/asr-voice`）依赖 office-kit 运行时中的 SenseVoice 引擎与模型，并可选调用
系统工具。**模块自身不打包下列系统工具**，它们由目标机或系统包管理器提供。

## 随 office-kit 运行时分发

| 组件 | 版本 / 文件 | 许可证 | 来源 |
| --- | --- | --- | --- |
| SenseVoiceSmall 模型权重 | `sensevoice-small-q8.gguf`（242.4 MiB） | **FunASR Model Open Source License 1.1** | 阿里巴巴通义实验室 / FunASR，ModelScope；量化 GGUF 版随 asr-now 分发 |
| llama.cpp（推理框架） | 随 `llama-funasr-sensevoice` 构建 | MIT | https://github.com/ggml-org/llama.cpp |
| FunASR 运行时代码 / `llama-funasr-sensevoice` | aarch64 可执行文件 3.7 MiB | MIT（Copyright © 2025 FunASR） | https://github.com/modelscope/FunASR ；aarch64 二进制由 asr-now 项目用 GCC 9.3 / CMake 4.4 自编译（构建日期以 `asr models` 输出为准） |
| CPython 运行时 | 3.12.15（`runtime/python`） | PSF-2.0 | https://www.python.org/ |
| 本模块代码 | `modules/asr/lib/asr_cli.py`、`bin/asr` | 随 office-kit 项目分发（与项目一致） | office-kit |

### SenseVoiceSmall 模型许可要点

模型权重不对应 OSI 许可证，而适用 **FunASR Model Open Source License Agreement 1.1**：

- 允许使用、复制、修改、分享；
- 分发或再发布时必须**保留来源与作者信息，并保留 SenseVoiceSmall 等模型名称**；
- 模型按「现状」提供，阿里巴巴集团不承担使用造成的直接/间接损失；
- 不得对模型/社区进行恶意贬损等违反协议精神的行为，否则许可自动终止。

完整文本见 asr-now 仓库 `licenses/SenseVoiceSmall-MODEL_LICENSE`，或 FunASR 模型页面。
对外分发 office-kit 时请保留本文件与模型名称、来源说明。

> 本模块**没有**引入 CT-Transformer 标点模型（Apache-2.0，约 285 MB）、Qwen3-ASR、
> sherpa-onnx、ONNX Runtime，因此无需附带它们的许可文本。

## 系统可选工具（不随 office-kit 分发）

以下工具按需探测；缺失时模块降级运行（例如 `input` 只打印文本）。

| 工具 | 用途 | 许可证 | 来源 |
| --- | --- | --- | --- |
| ffmpeg / ffprobe（系统 4.2.2） | 任意音频 → 16 kHz 单声道 WAV、时长探测、libflite 测试语音 | GPL-2.0+（Kylin 构建启用了 GPL 组件；上游核心为 LGPL-2.1+） | https://ffmpeg.org/ |
| alsa-utils / arecord（1.2.2） | 麦克风录音、设备枚举 | GPL-2.0 | https://www.alsa-project.org/ |
| wl-clipboard（`wl-copy`） | Wayland 剪贴板 | GPL-3.0+ | https://github.com/bugaevc/wl-clipboard |
| xclip | X11 剪贴板 | GPL-2.0+ | https://github.com/astrand/xclip |
| xsel | X11 剪贴板后备 | X11 License（MIT 风格） | https://github.com/kfish/xsel |
| xdotool（1:3.20160805.1） | X11 模拟 Ctrl+V | BSD-3-Clause | https://github.com/jordansissel/xdotool |
| ydotool（若安装） | Wayland/通用模拟 Ctrl+V（`ydotool key 29:1 47:1 47:0 29:0`） | AGPL-3.0+ | https://github.com/ReimuNotMoe/ydotool |

说明：

- ffmpeg 的具体许可证取决于发行版编译选项；Kylin/Debian 默认包通常因启用 GPL 组件而按
  GPL-2.0+ 分发。office-kit **不重新分发** ffmpeg，只在运行期调用系统命令。
- `ydotool` 为 AGPL-3.0+；若对外分发包含 ydotool 的整体镜像，请遵守 AGPL 的源码提供义务。
  模块本身只通过子进程调用它。
- 测试脚本用 ffmpeg 的 `flite` 滤镜合成英文语音；libflite 为 CMU 的语音合成库，
  仅在测试阶段使用，不参与运行期识别。

## 参考实现

本模块的行为参考（未直接复制代码）了 asr-now Lite 0.6.0 的 CLI 调用方式、16 kHz 约定与
`SV_THREADS` 线程设置：

- https://github.com/modelscope/FunASR
- asr-now 项目（本地参考 `/home/link/桌面/code/asr-now`），其 README 许可章节列明：
  llama.cpp MIT、FunASR 及 `llama-funasr-sensevoice` 运行时代码 MIT、SenseVoiceSmall 模型
  权重适用 FunASR Model Open Source License 1.1。
