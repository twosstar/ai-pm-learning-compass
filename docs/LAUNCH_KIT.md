# 发布素材包 / Launch kit

状态：本地公开版的发布候选素材；不是已部署到公网或已推送 GitHub 的声明。

Status: launch-candidate materials for the local public edition, not a claim of a live hosted service or a completed GitHub push.

## 1. 项目名称与一句话介绍 / Name and tagline

**名称 / Name:** AI PM Learning Copilot

**中文：** 把知识学会，再走向下一步。面向 AI 产品经理学习与求职的本地学习工作台，连接课程、场景练习、反馈和断点续学。

**English:** Understand the knowledge. Make your next move. A local-first AI product-management learning workspace connecting structured lessons, scenario practice, feedback, and resumable progress.

## 2. GitHub 仓库简介 / Repository description

中文：面向 AI 产品经理学习与求职的本地学习助手：60 节课程、120 个知识点、150 张概念卡片，支持模型反馈与进度恢复。

English: Local-first AI PM learning copilot: 60 lessons, 120 knowledge points, 150 concept cards, scenario practice, model feedback, and resumable progress.

可选 topics / Suggested topics:

`ai-product-management`, `learning-assistant`, `interview-practice`, `local-first`, `fastapi`, `sqlite`, `rag`, `ai-agents`, `education`

Topics 描述项目主题，不表示已实现完整自动化 Agent、云服务或某项认证。

## 3. 中文发布帖草稿

最近整理了一个面向 AI 产品经理学习和求职的本地学习工作台：**AI PM Learning Copilot**。

我希望解决的不是“资料不够多”，而是看完概念后不知道怎么用、练过题不知道怎样改，以及隔几天回来不知道接着学哪里。

目前公开版提供：

- 10 个模块、60 节课、120 个固定知识点；
- “是什么、怎么用、应用边界”的精简讲解，配判断流程与原创案例；
- 150 张可搜索的概念卡片；
- 通用 AI PM 与 AI＋教育方向，第二节已有双方向精编案例；
- 接入自己的兼容模型后作答、查看反馈；模型不可用时保存回答，不生成假分数；
- 本地阅读位置、已读标记、草稿与练习记录，刷新或重新打开仍能继续。

Windows 用户安装 Python 后，可双击启动脚本。需要评分时在页面填写自己的模型配置；不需要把密钥写进公开项目。课程和概念浏览不调用模型，练习和评分可能产生供应商费用。

公开包不包含购买课程原文、视频、PPT、讲义或商业题库。它不是就业保证，也不是多用户云端 SaaS。欢迎反馈内容准确性、案例可读性和学习体验的问题。

发布时在这里补上真实仓库地址；在仓库地址和许可证尚未确认前，不要把本段写成“已经正式上线”。

## 4. English launch post draft

I have been building **AI PM Learning Copilot**, a local-first workspace for learning AI product management and practicing interview-relevant decisions.

The problem I wanted to address was not simply a shortage of resources. It was understanding a term without knowing when to use it, practicing without a clear improvement path, and returning a few days later without knowing where to continue.

The public edition currently includes:

- 60 lessons across 10 modules, with 120 stable knowledge points;
- concise explanations of what a concept is, how to apply it, and where its limits are;
- decision diagrams, original examples, and optional deeper explanations;
- 150 searchable concept cards;
- general AI PM and AI-in-education study directions, with bespoke two-track cases currently available in lesson 102;
- bring-your-own-model answer feedback, with saved but unscored answers when evaluation is unavailable;
- locally persisted reading positions, read markers, drafts, and resumable practice sessions.

On Windows, install Python and use the double-click launcher. Configure your own compatible model from the page when you want evaluation. Reading lessons and concepts does not call a model; practice and evaluation may incur provider charges.

The release does not bundle purchased course materials or commercial question banks. This is a local learning tool, not an employment guarantee or a multi-user hosted SaaS. The interface and teaching content are primarily Chinese; bilingual project documentation is provided.

Add the real repository link only after confirming the repository and license. Until then, describe this as a release candidate rather than an already launched hosted product.

## 5. 配图清单与位置 / Image placements

所有现有图片均为真实界面在临时环境中的截图；示例学习文字为演示输入，无真实用户记录或密钥。不要把离线状态图标成“AI 真实评分效果”。

All supplied images are real UI screenshots from a temporary demo environment. They contain demonstration inputs, not private user records or credentials. Do not label the offline screenshot as an actual AI assessment.

| 图片 / Image | 推荐位置 / Placement | 图注要点 / Caption |
|---|---|---|
| `images/learning-dashboard.png` | README 首图、发布帖第一张 / README hero, launch post lead | 续学入口与分别计量的学习进度 / Resume action and distinct progress metrics |
| `images/lesson-reader.png` | 教学结构介绍后 / After the instructional-design section | 精简要点、应用边界、流程与折叠详情 / Essentials, boundaries, diagram, optional depth |
| `images/concept-map.png` | 概念库功能后 / After concept-library description | 搜索与概念卡片，不是节点连线图 / Searchable cards, not a node graph |
| `images/practice-offline.png` | 模型异常处理或隐私说明 / Evaluation availability section | 未配置模型时保存回答、不计分 / Answer retained without an invented score |
| `images/mobile-dashboard.png` | 响应式体验、发布帖末图 / Responsive design section | 响应式网页，非原生 App / Responsive website, not a native app |

GitHub Markdown 可直接使用相对路径。社交平台建议上传原始截图文件，不截图聊天窗口。手机截图只作辅助展示；主图使用桌面首页，更容易看清课程与续学结构。

Use repository-relative image paths in GitHub Markdown. Upload the original screenshot files to social platforms instead of taking screenshots of this chat. Use the desktop dashboard as the primary image; the mobile view is supporting material.

## 6. 发布前必须确认 / Required before publishing

- **仓库与公开范围 / Repository and scope:** 确认目标仓库、名称和公开可见性。没有仓库地址时不要编造下载链接。 / Confirm the target repository and visibility; do not invent a download URL.
- **许可证 / License:** 当前尚未选定；确认代码归属和依赖条款后，由项目所有者明确许可。没有许可证时不要宣传为可任意复用的开源软件。 / No project license is selected; confirm ownership and dependency terms before choosing one. Do not imply unrestricted reuse.
- **内容检查 / Content review:** 人工抽查来源、表述和原创案例，自动检查不能替代权利与事实审查。 / Human review is still needed for provenance, explanations, and original examples.
- **隐私检查 / Privacy:** 检查待发布文件列表，排除 `.env`、数据库、草稿、备份、日志、浏览器状态和密钥。仅运行检查并不等于已经完成 staged diff 审查。 / Exclude private data and inspect the actual staged release diff.
- **实际供应商测试 / Real-provider check:** 使用自己账户小范围测试连接与评分，费用由供应商计收。自动化测试只用模拟或离线接口，不证明真实评分质量。 / A user-controlled provider smoke test is still needed; mock checks do not establish grading quality.
- **产品形态 / Product form:** 当前下载后在本机运行，不是已实现用户登录与云同步的托管网站，也不是现成桌面安装包。 / The current product runs locally after setup, not as a multi-user hosted service or packaged desktop installer.
- **推送确认 / Push authorization:** 只有明确确认目标和授权后才创建发布、推送或部署。 / Publish, push, or deploy only after explicit target confirmation and authorization.

详细文案见 [中文项目介绍](PROJECT_INTRO.zh-CN.md) 和 [English introduction](PROJECT_INTRO.en.md)。
