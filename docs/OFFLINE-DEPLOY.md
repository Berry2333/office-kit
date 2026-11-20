# 离线部署手册

适用：内网 / 保密环境，目标机 **aarch64**、glibc ≥ 2.31、无外网、无 root。

## 一、构建机准备（只需一次，可联网）

```sh
cd office
bash build/build-appimage.sh          # 产物 dist/office-kit-1.0.0-linux-arm64.AppImage
```

构建脚本会自动：组装 AppDir → 复制 runtime（JRE/Node/Python/Stirling/模型）→
打包 zstd AppImage → 生成 sha256。

## 二、拷贝到目标机

需要拷贝两类东西：

```
office-kit-1.0.0-linux-arm64.AppImage      程序本体（约 1 GB）
skills/                                     5 个技能目录
install.sh                                  安装脚本（可选）
```

推荐目录：

```sh
mkdir -p ~/apps ~/.dsh/skills
cp office-kit-1.0.0-linux-arm64.AppImage ~/apps/office-kit.AppImage
chmod +x ~/apps/office-kit.AppImage
cp -r skills/* ~/.dsh/skills/
```

## 三、免安装使用

```sh
~/apps/office-kit.AppImage --help
~/apps/office-kit.AppImage pdf --help
```

若提示 FUSE 不可用：

```sh
~/apps/office-kit.AppImage --appimage-extract-and-run --help
# 或安装 libfuse2（麒麟一般已装）
```

## 四、注册为 DSH 技能

技能根目录按 DSH 规则为 `${DSH_HOME:-~/.dsh}/skills/<name>/SKILL.md`。
`install.sh` 会自动创建 `~/.local/bin/office-kit` 软链，并复制 5 个技能：

```sh
cd /path/to/office
./install.sh
```

验证：新开一个 DSH 会话，技能列表应出现
`office-docs`、`pdf-tools`、`ofd-tools`、`ocr-tools`、`asr-voice`。

## 五、技能如何调用

技能正文统一使用 `office-kit` 命令。如果目标机 `PATH` 里没有它，技能里提供了回退：

```sh
KIT="${OFFICE_KIT_BIN:-$HOME/apps/office-kit.AppImage}"
"$KIT" office convert --input a.docx --output a.pdf
```

也可以把 `OFFICE_KIT_BIN` 写进 shell 配置或 DSH 的环境变量。

## 六、数据与缓存

> **AppImage 模式首次使用 PDF 功能**会把 PDF 引擎（jar/native/tessdata/JRE/glibc，约 390 MB）
> 解包到 `~/.local/share/office-kit/pdf/runtime/`，因为 AppImage 启动进程退出后挂载会卸载，
> 后台 JVM 需要稳定路径。只解包一次，后续 `start` 秒级复用。可用
> `OFFICE_KIT_PDF_STAGE=0` 关闭（自行保证引擎路径稳定）。

| 路径 | 内容 |
| --- | --- |
| `~/.local/share/office-kit/pdf/` | Stirling 配置/日志/工作目录/端口 |
| `~/.local/share/office-kit/cache/` | 转换中间文件（可随时删） |
| `~/.local/share/office-kit/logs/` | 各模块日志 |

可用 `OFFICE_KIT_DATA` 整体改位置（建议放本地盘，不要放网络盘）。

## 六点五、卸载

```sh
./uninstall.sh --dry-run     # 先看会删什么
./uninstall.sh               # 停后端 + 删技能/shim/AppImage（保留数据）
./uninstall.sh --purge       # 连数据目录一起删
./uninstall.sh --keep-appimage
```

卸载只删除 `~/apps/office-kit.AppImage`、`~/.local/bin/office-kit`、
`~/.dsh/skills/{office-docs,pdf-tools,ofd-tools,ocr-tools,asr-voice}`；
数据目录 `~/.local/share/office-kit` 默认保留，确认不再使用再加 `--purge`。

## 七、常见问题

**Q: 双击/运行没反应？**
`chmod +x`；用终端运行看 stderr；确认 `uname -m` 是 aarch64。

**Q: PDF 功能第一次很慢？**
Stirling 后端冷启动 20–40 s，属正常；之后常驻。`office-kit pdf status` 可查。

**Q: 内存不够？**
`export OFFICE_KIT_JAVA_OPTS="-Xmx1g"`；或处理完立即 `office-kit pdf stop`。

**Q: 中文 PDF 字体不对？**
LibreOffice WASM 使用宿主字体；把中文字体放进 `~/.fonts` 后重试，
或给 `office render/convert` 加 `--font-dir /path/to/fonts`。

**Q: 语音识别没有声音输入？**
`office-kit asr devices` 查看设备；容器/远程桌面里通常没有麦克风，
改用 `asr file` 处理已有音频。

## 八、内网批量分发

```sh
# 制作分发包
tar czf office-kit-offline.tar.gz \
  dist/office-kit-*-linux-arm64.AppImage dist/*.sha256 skills install.sh

# 目标机校验
sha256sum -c office-kit-*.sha256
```
