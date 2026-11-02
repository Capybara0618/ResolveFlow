# 蓝白立体架构图与动态预览

2026-11-02。用户指定此前被替换的蓝色插画架构图为风格参考，要求绘图质量、现代感、动态效果和清晰结构。参考为 `docs/assets/readme/architecture-v2.png`，并非后续绿色简化SVG。

使用内置 image_gen，引用本地已审看原图重绘。完整生成提示词见同目录 `architecture-blue-20261102.prompt.txt`。新图 `docs/assets/readme/architecture-blue-v3.png`，1586×992、1,707,556字节；原蓝图、当前README图片和SVG均保留，不自动替换已发布引用。

核对实际网关路由及系统设计：Gateway直接分流Commerce与Case；Case/Commerce的HTTP协作与绿色MQ退款路径分开；账户模块明确暂在Case，媒体同进程边界在图底说明；各自业务库、Agent职责与共享Redis可见。HTTP双向箭头包含请求/响应，图片的流动效果不表示测量时延或强制Agent工具顺序。

动态预览 `docs/assets/readme/architecture-blue-v3.html` 保留生成图原始像素，在连线上叠加移动光点，提供完整/购物/售后/退款/身份五种链路、暂停/继续，以及减少动态效果支持。无需启动业务服务，不调用网络API或模型。只使用旁边的PNG，可直接本地打开。

实际验证：`agent/.venv/Scripts/python.exe tmp/check_blue_architecture.py`，独立Edge headless/CDP，1280与430宽度均无横溢、图片实际加载1586×992；22光点坐标随时间改变；退款筛选8光点、身份筛选2光点及说明同步；暂停后坐标固定；prefers-reduced-motion默认暂停；0运行异常。截图 `tmp/architecture-blue-20261102/preview-1280.png`、`preview-430.png` 及 `verification.json` 保留，桌面截图已审看。

原本进行的Jev业务改动、数据库、运行进程与任务账本不在本次修改范围；本次只新增图、预览和生成/检查记录，避免与正在更新的任务账本并行写入。

## 作者确认并替换GitHub正式图片

作者随后指定上传的确认稿，明确要求直接替换GitHub图片。将该附件原字节复制到README已引用的 `docs/assets/readme/architecture-rounded.png`，不重新生成/压缩/裁切。确认稿1586×992、2,076,865字节、SHA256 `4619ecb7513b71483e32b3ecdc75ff285767959e569c799e0a7668fe438b9e80`；与生成副本的RGBA像素摘要相同，文件编码不同，发布以作者附件为准。

README原相对链接保持；`docs/system-design.md`的图引用同步指向这张确认稿。早期蓝图 `architecture-v2.png`、可编辑SVG和动态预览本地文件保留。提交仅包含正式PNG、系统设计图引用及本检查/提示词；不夹带Jev工作、其他暂存内容或修改并行更新的任务账本。图片/路径/差异检查后正常中文commit与push，远端图片字节与确认稿再次核对。
