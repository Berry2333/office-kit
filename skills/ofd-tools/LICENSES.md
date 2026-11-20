# ofd-tools 第三方组件与许可

本技能由 office-kit 的 `modules/ofd` 模块提供，运行期只使用 `modules/ofd/lib/jars/` 下
的 39 个 jar（约 28 MB）和 `runtime/jre`（Temurin 25）。除下列组件外，模块自身源码为
office-kit 原创（Apache-2.0 兼容使用）。

## 1. 核心库

| 组件 | 版本 | 许可证 | 上游 / 用途 |
| --- | --- | --- | --- |
| OFD R&W（ofdrw-converter / core / font / gm / graphics2d / gv / layout / pkg / reader / tool） | 2.5.1 | Apache-2.0 | https://github.com/ofdrw/ofdrw — OFD 读写、转 PDF/HTML、合并、PDF 转 OFD |
| Apache PDFBox（pdfbox / fontbox / pdfbox-io） | 3.0.8 | Apache-2.0 | https://pdfbox.apache.org/ — PDF 生成、页数复核、PNG 栅格化 |
| Apache Batik（batik-all） | 1.19 | Apache-2.0 | https://xmlgraphics.apache.org/batik/ — ofdrw SVG 生成（to-html） |
| Apache XML Graphics Commons | 2.11 | Apache-2.0 | https://xmlgraphics.apache.org/commons/ — Batik 依赖 |
| Bouncy Castle（bcprov / bcpkix / bcutil `-jdk18on`） | 1.85 | Bouncy Castle Licence（MIT 风格） | https://www.bouncycastle.org/ — ofdrw 的 SM2/SM3 等算法 |
| dom4j | 2.1.4 | BSD 风格（Plexus / dom4j License） | https://dom4j.github.io/ — XML 解析 |
| Jaxen | 1.2.0 | BSD 2-Clause | https://github.com/jaxen-xpath/jaxen — XPath |
| UJMP core | 0.3.0 | **LGPL-3.0** | https://github.com/ujmp/ujmp — ofdrw-converter 的矩阵运算依赖 |
| zip4j | 2.11.3 | Apache-2.0 | https://github.com/srikanth-lingala/zip4j — OFD ZIP 容器 |
| Apache Commons Compress | 1.28.0 | Apache-2.0 | https://commons.apache.org/proper/commons-compress/ |
| Apache Commons IO | 2.16.1 | Apache-2.0 | https://commons.apache.org/proper/commons-io/ |
| Apache Commons Lang3 | 3.18.0 | Apache-2.0 | https://commons.apache.org/proper/commons-lang/ |
| Apache Commons Codec | 1.19.0 | Apache-2.0 | https://commons.apache.org/proper/commons-codec/ |
| Apache Commons Logging | 1.4.0 | Apache-2.0 | https://commons.apache.org/proper/commons-logging/ |
| SLF4J API / NOP | 1.7.36 | MIT | https://www.slf4j.org/ — 日志门面；NOP 用于静默 ofdrw 内部日志 |
| xml-apis / xml-apis-ext | 1.4.01 / 1.3.04 | Apache-2.0（含 W3C 文档许可） | https://xml.apache.org/commons/ |
| TwelveMonkeys ImageIO（imageio-core / metadata / tiff，common-image / io / lang） | 3.13.0 | Apache-2.0 | https://github.com/haraldk/TwelveMonkeys — PDFBox 图像解码 |
| jbig2-imageio | 3.0.5 | Apache-2.0 | https://github.com/levigo/jbig2-imageio — PDF 内 JBIG2 图像 |
| org.json（json-20141113） | 20141113 | **JSON License**（MIT + “The Software shall be used for Good, not Evil”） | https://json.org/license.html — 间接依赖 |

> 说明：
> - **UJMP core 为 LGPL-3.0**，仅由 `ofdrw-converter` 内部调用，以未修改的独立 jar 形式随包分发；
>   如对外再分发，请保留其许可声明并遵守 LGPL 关于替换库的要求。
> - **org.json 的 JSON License** 含 “Good, not Evil” 条款，OSI 未认证；本模块未直接调用，
>   仅作为 ofdrw 依赖链的一部分随包提供。对许可证合规要求严格的场景，可联系上游移除此依赖。

## 2. 运行时与构建工具

| 组件 | 版本 | 许可证 | 说明 |
| --- | --- | --- | --- |
| Eclipse Temurin JRE（`runtime/jre`） | 25.0.4.1 | GPL-2.0-with-Classpath-Exception | 由 office-kit 主运行时提供，本模块只调用 |
| Temurin JDK | 21.0.13+9 | GPL-2.0-with-Classpath-Exception | **仅构建期**使用，下载到 `.tmp/ofd/jdk`，不入库 |
| Apache Maven | 3.9.16 | Apache-2.0 | **仅构建期**使用，下载到 `.tmp/ofd/maven`，不入库 |
| Maven 依赖（Maven Central / 阿里云镜像） | — | 各自上游许可 | **仅构建期**下载到 `.tmp/ofd/m2`，不入库 |

## 3. 演示字体

`modules/ofd/testdata/fonts/ofd-demo-cjk.ttf`（41 KB）是两个字体的子集合并产物，仅用于
`ofd demo` 生成自检 OFD，不参与用户文档的字体替换：

| 来源 | 许可证 | 版权 |
| --- | --- | --- |
| Droid Sans Fallback（`DroidSansFallbackFull.ttf`） | Apache-2.0 | Copyright (c) 2006-2010 Google Inc. |
| DejaVu Sans（`DejaVuSans.ttf`） | Bitstream Vera Fonts License | Copyright (c) 2003 by Bitstream, Inc. |

完整许可文本见 `modules/ofd/testdata/fonts/LICENSE.txt`；字符清单见
`modules/ofd/testdata/demo-chars.txt`。字体已重命名为 “OfficeKit Demo CJK”
（不含 Bitstream / Vera 字样），符合两段许可对修改版本命名的要求。

## 4. 合规提示

- 本模块运行时**不联网**，不下载任何字体或模型；所有 jar、字体、class 均已随仓库分发。
- 若将 `modules/ofd/lib/jars/` 随 AppImage 一起分发，请一并保留本文件及 jar 内的
  `META-INF/LICENSE` / `META-INF/NOTICE`（未删除）。
- 用户文档的版权与内容责任由使用者承担；本模块不上传、不收集任何文档内容。
