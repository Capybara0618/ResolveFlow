# README 影片首版交付（2026-10-29）

卡皮巴拉专用账号的一笔329元耳机订单已完成真实操作录制，首版动图、两支配乐视频、封面及角色截图已生成。当前交作者审片，正式README接入和视频公开发布待审片后进行。

## 交付清单

制作目录为 `tmp/product-film-clean-20261029/`，以下成片位于其 `delivery/`，均已检查完整解码：

| 文件 | 时长 | 大小 | 格式 |
| --- | --- | --- | --- |
| product-film.mp4 | 90秒 | 4,951,612字节 | 1920×1080，H.264，30fps，AAC双声道 |
| full-demo.mp4 | 220秒 | 10,490,845字节 | 1920×1080，H.264，30fps，AAC双声道 |
| experience.gif | 28秒 | 1,479,213字节 | 宽1080，280帧，10fps |

同目录保存两份SRT字幕、两份剪辑表、`verification.json`及`MUSIC-NOTES.md`。候选README素材在 `docs/assets/readme/`：`experience.gif`、`demo-cover.png`、`full-demo-cover.png`、`buyer-confirm.png`、`merchant-review.png`、`operations.png`、`buyer-result.png`。本步未将待审媒体加入Git。

审阅页为 `web/public/tmp/readme-film-review-20261029/index.html`，运行网页后访问 `/tmp/readme-film-review-20261029/index.html`，可播放两支视频、查看动图和角色截图。审阅页及制作目录均忽略，不包含在本次源码提交中。

## 同笔订单与业务核对

- 买家：`demo_showcase`，显示名卡皮巴拉，使用用户指定水豚头像。拍摄前0订单、0咨询；拍摄后1订单、1咨询，不混入旧buyer10素材。
- 商品：P-1001无线降噪耳机，黑色1件，松间数码M-1001，实付32900分。
- 订单：`fe1c10af-e37e-46b4-9da6-d36f498c55aa`，订单行 `SHOP-db010f11-e251-4a1a-a2dd-625ff5bc5886`。
- 申请：`8371b925-c264-49f2-ad5e-f2464ad0a5fe`，最终 `CLOSED_SUCCESS`。
- 调查：revision1的 `13723f27-94ac-5765-8ff3-917625f0b651` 正常完成并交人工核验；商家补充核验材料后，revision2的 `5947bcad-e564-5643-b7e1-2d8e1d23ac42` 正常完成，Java校验建议后允许商家批准。
- 实际模型请求23次：3次咨询合计11次模型请求，两轮调查各6次。包含未剪入成片的完成追问，不以剪辑次数代替调用次数。
- 正式查询确认同行成功退款操作仅1笔、32900分；账本实付32900、已退32900、预留0。付款、发货、确认申请、商家核验及审批、买家结果跳转均实际操作。交易与物流使用项目模拟能力。

服务由 `start.ps1 -SkipBuild -NoBrowser` 启动。新订单先在商家页面发货，再用 `scripts/logistics_simulator.py inspect/advance` 按当前版本2推进本订单LOST版本3，使用固定请求键 `film-capybara-20261029-lost`。没有直接改写交易库或删除历史记录。

## 剪辑与配乐

原始12段浏览器CDP事件帧、动作与时间戳保存在制作目录 `raw/`。原始采集帧率随页面变化，成片为30fps编码输出。查询等待压缩、核验完成后的跳转有画面标识；同一片段内保留实际帧顺序。

成片剔除了CDP偶发捕获到的瞬时缩小画面，保留原始文件。首版静态买家确认图选取提交前真实确认卡，封面采用实际界面裁切。片头、字幕、服务关系说明为剪辑图层。

配乐由本次 `build_film.py` 的 `music()` 程序合成：96 BPM、C大调，电钢琴、铺底、低音与轻节拍，四处合成提示音。没有引入外部录音或第三方采样。影片包含配乐轨；主观听感、字幕节奏与营销表达交作者审阅。

## 实际检查

命令在制作目录使用现有 `agent/.venv/Scripts/python.exe` 执行，FFmpeg沿用已准备的 `tmp/product-film-20261029/media-deps/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe`：

```powershell
.\agent\.venv\Scripts\python.exe tmp/product-film-clean-20261029/build_film.py promo
.\agent\.venv\Scripts\python.exe tmp/product-film-clean-20261029/build_film.py demo
.\agent\.venv\Scripts\python.exe tmp/product-film-clean-20261029/build_film.py gif
.\agent\.venv\Scripts\python.exe tmp/product-film-clean-20261029/finish_assets.py
.\agent\.venv\Scripts\python.exe tmp/product-film-clean-20261029/prepare_review.py
```

- 两支MP4全片FFmpeg解码至null通过；音视频时长90/220秒、分辨率、帧率、AAC双声道符合清单。
- `volumedetect`：宣传片平均−22.2 dB、峰值−8.4 dB；完整演示平均−21.8 dB、峰值−8.4 dB。
- PIL检查GIF累计28000ms、280帧、宽1080；关键帧和最终封面实看过。
- 审阅页浏览器实机点击播放宣传片，确认播放时间推进；两播放器时长90/220秒、视频尺寸1920×1080、媒体错误为空；无水平溢出、无失效图片。检查后页面重载为暂停，留待作者播放。
- 业务证据保存在忽略目录的 `audit-public.json`、`verification.json`；会话令牌及凭据不进入本报告或Git。
- 最终文件SHA-256：宣传片 `d663142d171f60ece9c33a9586ec64ec21b5cb191ebd46f32d7a6cc72b68d802`；完整演示 `cc401d7c0f4cf54c825a36af1d353c7f5eb42f69232f2808560270d2cda16cfa`；动图 `aaec5ea5bfd2d2be2a115c97ab829e46c16f792103f37fa74ba02bf930db679d`。

## 保留问题与下一步

完成追问的实际回复包含“后续可留意退款到账情况”，与模拟交易表达不够贴合，该段未剪入三份成片，原始记录保留。录制时有一帧鼠标悬停主按钮文字对比度偏低，静态封面未选该帧，本轮未修改业务页面。首版交付不代表额外完成了一轮全项目功能验收。

服务继续运行，作者可直接审阅成片。下一步根据审片意见调整节奏、字幕和配乐，定稿后再将交付媒体纳入仓库、公开发布视频并接入正式README。
