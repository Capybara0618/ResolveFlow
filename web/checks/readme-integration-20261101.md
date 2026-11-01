# 正式README展示素材接入

2026-11-01，作者确认第二版简洁圆角排版及三张大图/25fps动图，授权更新正式README。

## 实现

- README顺序为封面、完整视频、关键流程动图、三端大图、技术栈、微服务架构、核心设计和快速开始。三张界面图各占一行，角色名独立居中放在图下，无额外小字说明。
- 新增10个最终媒体文件至docs/assets/readme，合计6,188,307字节；.gitignore仅逐文件放行本次素材。既有蓝色封面、概览、流程和原架构图保留，原四历史脏文件不变。
- 圆角封面、技术栈、架构与设计块由已确认HTML导出2倍分辨率PNG；三端分别导出完整16:10圆角图。正式README使用图片、标题、picture和链接，不依赖自定义CSS/脚本。
- 技术栈与核心设计分别提供桌面/手机图片，picture在600px以下选择手机排版，避免把桌面两列文字缩成小字。描述与指标含义同步保留在alt；详细条件继续链接原docs/evaluation-results.md，未重测或改写历史指标。
- 25fps GIF保持960×600、20秒、421个合并后有效帧、最短40ms、1,925,170字节，SHA256 `cd85005f1d2db5032f601da3b8feba2804647716ffda5989d8496eb808d3d251`。本轮不重新编码GIF或定稿视频。

## 完整视频

作者已确认的自选配乐v4作为原文件上传至本仓库关联的GitHub视频附件：

https://github.com/user-attachments/assets/34304069-e2da-4552-ac25-2443e1b759d3

111.90秒、2560×1600、60fps、15,323,610字节，SHA256 `8f35fd19991336c95ae608b9b7ff1dc7b49b2968155747922afff4d0f3350a31`；配乐来自作者提供的bgm.mp3。下载附件并完整计算SHA256，字节数及摘要与定稿一致，没有改变画质、帧率或音轨。未提交原MP3/完整MP4到Git，不改变仓库访问设置。

现有gh2.96不含--attach；核对[GitHub官方附件文档](https://docs.github.com/en/github-cli/github-cli/attaching-files-with-github-cli)与[官方CLI2.99附件客户端源码](https://github.com/cli/cli/blob/v2.99.0/internal/attachments/client.go)后，复用其官方上传协议，仅上传视频附件，不创建Issue/评论/Release。凭据只在进程内读取，未写文件或提交。POST201后将附件地址持久化，重试复用同一上传记录。

## 实际验证

使用现有Python/httpx/Pillow、FFmpeg、gh和Edge，无新依赖、无业务服务启动/业务写入/模型请求。

1. `tmp/readme-integration-20261101/export-reviewed-assets.py`复核原审核稿并导出单张圆角图及手机技术图。桌面1160/手机430无溢出、图片加载、角色下置通过；原完整视频在静音条件下实播并跳到74秒。
2. `upload-video.py`按正式文件摘要校验后上传，`video-upload.json`保存持久附件地址；附件GET200/video/mp4，完整下载与原片SHA256一致。
3. `gh api markdown -F text=@README.md -f mode=gfm -f context=Capybara0618/ResolveFlow`实际返回一个原生video和两组保留media条件的picture；不是把MP4文本链接称作播放器。GitHub会增加自己的视频边框、文件名和播放控件，这些属于平台呈现。测试自定义poster/width属性会被平台移除，因此最终沿用官方附件渲染，不依赖该属性。
4. `verify-readme.py`核实13个仓库内路径、10张图片/动图、忽略规则、GIF帧时长、无临时路径或自定义CSS/脚本；正式文件与素材摘要清单记录在忽略目录。
5. `render-final.py`使用GitHub API产生的实际HTML正文，在独立Edge headless/CDP中检查1160/430布局。图片加载、无横溢、三个角色均位于图下、手机/桌面picture实际选择正确，视频可静音播放，参数读回2560×1600/111.90秒；整页及媒体截图已查看。该检查在原生HTML正文加最小排版样式后进行，视频改用同字节原文件，不能称为登录态GitHub远端页面逐屏验收。
6. .gitignore、README及本步文档`git diff --check`通过。本批为文档/媒体，不重复运行应用测试。上传源/远端回读、脱敏排版稿、截图与校验脚本均留`tmp/readme-integration-20261101/`，签名媒体地址不写入正式README。

首次apply_patch将同文件删除/新增合并提交而被工具拒绝，未改动README；改为先生成完整最终稿再复制成功。视频原生播放器的自动生成HTML包含短期签名地址，该HTML只留忽略目录；正式README始终使用稳定附件地址。原四个历史改动保持，不纳入本步提交。
