# 展示链字体（2026-10-28）

界面与操作使用Noto Sans SC，正文阅读使用Noto Serif SC；运行时同源加载WOFF2，不依赖访问者预装字体或第三方字体服务。仅首页/列表与买家咨询、退款确认、单商家审批作用域采用本批排版，其他页面保留现状。

来源为本机已安装的`NotoSansSC-VF.ttf`和`NotoSerifSC-VF.ttf`。字体原始版权、版本、许可证声明、源文件SHA256、转换中间产物SHA256以及最终各文件SHA256记录在`provenance.json`。这些名称指Noto SC字体，不能当作Claude实际字体的确认。Sans源标注Version 2.04、Serif源Version 2.02，均保留原始non-release版本字符串，不包装成另外的正式版本。

两字体采用SIL OFL 1.1。官方许可原文分别来自[Google Fonts Noto Sans SC](https://github.com/google/fonts/blob/main/ofl/notosanssc/OFL.txt)和[Noto Serif SC](https://github.com/google/fonts/blob/main/ofl/notoserifsc/OFL.txt)，本目录保存对应OFL原文；原字体版权也保留在二进制name表和provenance中。

资源构建：

```powershell
uv run --no-project --with 'fonttools[woff]==4.60.1' python web/tools/build_display_fonts.py C:/Windows/Fonts/NotoSansSC-VF.ttf C:/Windows/Fonts/NotoSerifSC-VF.ttf
```

命令在仓库根目录执行。只使用一次性工具缓存，不更改项目运行依赖或锁文件。输入文件不入库、不修改；Sans保留400–600可变字重，Serif固定400。输出为本目录字体、provenance及`web/src/ui/display-font-faces.css`；不手工编辑生成CSS。转换会校验源字符集合，随后将GB2312一级常用字、符号与静态UI字符放入common文件，其余字符由不重叠的unicode-range按需使用extended文件，声明的字符集合并集保持源覆盖。字体整形闭包可以保留来源字体已有的额外编码别名，但不能丢失声明字符或引入源外字符。

Sans common约1.12MB，Serif common约0.85MB；extended保留完整转换字库以覆盖不常用字符，分别约7.38MB/5.73MB，仅出现对应字符时加载。`font-display: swap`保留加载期间的系统字体回退。该取舍优先保证当前小项目的字形覆盖和离线同源体验，并不宣称已做到最小中文字体分片；包含罕见字的首次加载仍可能较大。没有预加载全部字库。

构建中间整套WOFF2完成校验后移除，最终只交付common和extended。早期逐Unicode块分片尝试及自动别名检查失败保留在本机`tmp/typography-review/`，没有作为页面验收成功依据。正常生成不要求或执行模型调用、业务HTTP或数据库操作。
