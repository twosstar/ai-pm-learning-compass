# AI PM 学习罗盘 V2.0

面向 AI 产品经理学习者与求职者的 Windows 桌面学习工具。按课程建立知识框架，用业务场景练习判断，通过反馈和错题复盘持续改进。

## 页面预览

| 学习首页 | 场景练习 |
|---|---|
| [![学习首页](docs/images/learning-dashboard.png)](docs/images/learning-dashboard.png) | [![场景练习](docs/images/practice-question.png)](docs/images/practice-question.png) |
| **答题反馈** | **概念地图** |
| [![答题反馈](docs/images/score-feedback.png)](docs/images/score-feedback.png) | [![概念地图](docs/images/concept-map.png)](docs/images/concept-map.png) |

### 一张完整的知识卡片

概念卡不只给出定义，也会说明它怎么运作、适合解决什么问题、有哪些使用边界，以及 AI 产品经理该怎么判断。

[![检索增强生成（RAG）完整知识卡片](docs/images/concept-card-full.png)](docs/images/concept-card-full.png)

## 主要功能

- **系统学习：** 10 个主题模块、60 节课程、120 个知识点。
- **求职练习：** 通过 AI 产品业务题练习需求判断、技术取舍与风险处理。
- **答题反馈：** 查看得分、回答亮点、待补充内容和参考表达；模型不可用时会保存答案并标记待评价，不会编造分数。
- **错题复盘：** 保存题目、自己的作答、参考答案和评分；可重新回答并再次评价。
- **概念地图：** 按主题查阅 150 张概念卡，了解概念用途、适用场景和使用边界。
- **本机进度：** 学习记录保存在当前电脑，可回来继续学习；不提供账号或云同步。

## 安装使用

1. 打开[最新版本下载页](https://github.com/twosstar/ai-pm-learning-compass/releases)。
2. 下载名称以 `AI-PM-Learning-Compass-Setup` 开头的 Windows 安装包，双击并按提示安装。
3. 从桌面或开始菜单打开“AI PM 学习罗盘”。无需安装 Python 或单独购买服务器；电脑需要 Microsoft Edge WebView2 Runtime。

首次安装会从空白进度开始，不包含开发者的学习记录或模型密钥。正式版本发布后，应用会检查更新并提示安装。

## AI 评分与数据

AI 评分需要你在应用内配置自己信任的模型服务商、模型名称和 API 密钥，调用费用由你承担。练习或评分时，题目、相关课程内容及你的回答会发送给所选服务商。

学习记录保存在本机。API 密钥可选择只在本次运行中使用，或保存到当前 Windows 用户的凭据保险库。请勿把密钥提交到仓库。

## 项目内容

课程与概念卡为本项目独立整理和编写，不收录任何课程原始视频、讲义、逐字稿或专有题库。来源范围见[课程来源说明](CURRICULUM_SOURCES.md)。
