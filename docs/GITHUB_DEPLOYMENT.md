# GitHub 发布说明

- 源码仓库：https://github.com/usbfl/TracePatch
- 展示页：https://usbfl.github.io/TracePatch/
- 报告页：https://usbfl.github.io/TracePatch/report.html
- 发布目录：`main` 分支的 `/docs`，包含 `.nojekyll`、`index.html` 与 `report.html`。

## 首次开启 Pages

在仓库 Settings → Pages 中，选择 Deploy from a branch → main → /docs → Save。等待 pages build and deployment 成功，再访问展示页。

## 更新

修改 `docs/index.html`、`docs/report.html` 或 `docs/site.css` 并推送到 main 后，GitHub 自动重新发布。页面使用相对资源路径，兼容项目子目录；无外部字体、CDN 或模型调用。

## 版本与验证范围

这是已有项目的源码和静态报告发布。原版本测试记录的日期、结果和局限保持原义，不作为本次重新执行所有应用测试的声明。根目录原有 release / delivery manifest 描述原始交付包；本仓库文件清单见 `GITHUB_PUBLISH_MANIFEST.json`。

TracePatch 的报告来自原 v0.2 实际离线运行。大型 SQLite、检查点和历史实验输出不纳入 Git；本地运行脚本可重新生成。

真实 `.env`、个人数据库、虚拟环境及缓存不纳入发布。默认离线或 mock 配置保持不变。
