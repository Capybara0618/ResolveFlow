# README 简洁圆角版审核稿

2026-11-01，作者指出上一稿小字太多、视频入口不明显，要求清晰整洁、圆润现代，并明确保留视频和动图。本步调整审核稿，正式README.md、既有正式图片及定稿视频均未改。

## 设计调整

- 米色与绿色的简洁封面，用大标题表达产品；原蓝色封面保留，不覆盖。
- 先展示完整视频播放器，直接播放作者已确认的自选配乐v4，2560×1600/60fps/111.90秒；随后单独展示20秒自动循环GIF。两者均为大幅独立区域，不再将视频藏在动图下的小字链接中。
- 删除重复产品介绍、步骤串、图片下说明段落、前部页内小导航及折叠提示。三端界面只保留“买家/商家/平台”三个标题，点击图片查看原图。
- 技术栈按职责整理为六行；现有架构图随后呈现。六项核心设计采用圆角块，突出已有指标，同时保留成功率/命中率/上下文通过率及30并发p95等必要定义。完整条件和实现细节通过文档入口提供。
- 正文、分类与说明在桌面/手机均至少16px；手机命令块为14px，方便保留命令结构。避免依靠小字号压缩内容。
- 圆角封面为原生SVG；技术栈、设计块、三端图及架构已导出2倍分辨率PNG，以便正式Markdown使用图片承载圆角和间距，不依赖GitHub保留自定义CSS。草稿README.expected.md已准备。

## 审核入口

`http://127.0.0.1:8766/readme-preview-v2/`

文件在`tmp/film-edit-v1-20261031/readme-preview-v2/`：index.html（实际播放器/动图）、static.html（仅为截图固定GIF帧）、README.expected.md、verify-preview.py、verification.json、readme-media.png、readme-desktop.png、readme-mobile.png和assets。此前/readme-preview/保留供比较；定稿视频主页保持。

商城封面改取1.mp4的2.0秒完整首页帧，避免使用已经向下滚动、横幅标题被切掉的帧。所有业务图片仍来自作者原录屏，未改商品、金额或消息。主视频直接引用原定稿文件，不重新剪辑、压缩或混音。

## 实际验证

现有预览服务跨日已停止，首次HTTP连接失败；恢复原serve.py后正常。未启动业务服务或调用模型。

执行`agent/.venv/Scripts/python.exe tmp/film-edit-v1-20261031/readme-preview-v2/verify-preview.py`，独立Edge headless profile/CDP，禁用浏览器缓存后集中验证：

- 桌面1160px和移动430px：scrollWidth与视口一致，全部图片和视频元数据加载；正文无小于16px元素，手机仅PRE为14px。整页截图与媒体区域截图已查看，圆角、主次与图文正常。
- 完整视频在浏览器静音条件下实际开始播放，读取2560×1600/111.90秒；播放按钮隐藏正常；跳到74秒后成功解码，readyState4。未人工试听音响，不把静音检查称为听感验收。
- GIF保持960×600、139有效帧、20秒、1,039,390字节；实际页面加载通过。播放器和动图分别存在且相互独立。
- HTTP预览页/封面/动图200、MP4 Range206；旧审核入口和视频主页保持。正式README无差异，原四历史脏文件未改动。
- 二倍PNG导出用于版式可移植性。它们及审核媒体均留忽略目录，尚未放入正式README或对公网发布。

GitHub最终视频接入将采用其上传附件生成的媒体地址；本次审核播放器指向现有文件，不把本稿当作已验证的GitHub线上播放器。[GitHub官方视频说明](https://github.blog/changelog/2021-05-13-video-uploads-now-generally-available/)及[附件文档](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files)已核对；自定义页面CSS不是正式README的依赖。正式接入及其实际渲染待作者审核后执行。
