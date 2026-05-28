# 生图 URL 返回兼容设计

## 背景
当前项目的非插件生图流程支持两类图片返回：

- `b64_json`：在 `bot/chatgpt.py` 中落地到临时文件后发送
- 绝对 URL：由各个 channel 在发送前自行下载或透传

新增的图片接口返回格式为：

```json
{
  "created": 1776582860,
  "data": [
    {
      "url": "/p/img/img_xxx/0?exp=...&sig=..."
    }
  ]
}
```

这里的 `url` 可能是相对路径。现状中，这类值会被直接当作本地文件路径发送，导致 `文件不存在`。

## 目标
在不影响现有生图能力的前提下，兼容以下输入：

- `b64_json`
- 绝对图片 URL（`http://` / `https://`）
- 相对图片 URL（如 `/p/img/...`）
- 本地文件路径

## 非目标
- 不修改 plugins 插件生图逻辑
- 不改变文本回复、视频回复流程
- 不依赖新第三方库

## 根因
- `bot/chatgpt.py` 在收到 `data[0].url` 时直接返回 `ReplyType.IMAGE`
- `channel/weflow.py` 仅当内容包含 `://` 时才按远程 URL 下载
- 相对 URL 不满足远程 URL 判断条件，最终进入 `wechat_sender.py` 被当作本地路径

## 方案
采用“双层兼容”方案：

### 1. bot 层规范化图片 URL
在 `bot/chatgpt.py` 中新增相对 URL 规范化逻辑：

- 若 `url` 已是绝对 URL，则保持不变
- 若 `url` 为相对 URL，则优先基于 `create_image_api_base` 进行补全
- 若未配置 `create_image_api_base`，则回退到 `openai_api_base`
- 若两者都没有，则保持原值并记录日志

示例：

- `create_image_api_base = http://192.168.1.26:8080/v1`
- `url = /p/img/...`
- 规范化结果：`http://192.168.1.26:8080/p/img/...`

### 2. 公共序列化层兼容相对 URL
在 `utils/serialize.py` 增加通用工具：

- 判断一个值是否为远程媒体引用
- 将相对 URL 规范化为可下载的绝对 URL

`serialize_img()` / `serialize_video()` 在下载前统一走该逻辑，使下载入口本身具备兼容能力。

### 3. channel 层补齐兜底
同步修正：

- `channel/weflow.py`
- `channel/wechat.py`
- `channel/wrest.py`

确保它们在判断“是否需要下载远程图片”时，不只识别绝对 URL，也能识别相对 URL；同时保留原有本地路径、base64、绝对 URL 的处理方式。

## 兼容性要求
- 原有 `b64_json` 逻辑不变
- 原有绝对 URL 生图逻辑不变
- 原有本地图片路径发送逻辑不变
- 新增相对 URL 兼容不应影响视频逻辑

## 测试策略
新增自动化测试覆盖：

1. 相对 URL 能被补全为绝对 URL
2. 绝对 URL 保持不变
3. 本地路径不被误判为远程 URL
4. `ChatGPTBot` 处理相对 URL 时返回规范化后的图片地址
5. `ChatGPTBot` 处理 `b64_json` 时仍会生成本地临时文件

## 风险与控制
- 风险：误把普通字符串当作相对 URL
  - 控制：仅在明显不是本地已存在文件、也不是 `base64://`、且具备 URL 路径特征时才补全
- 风险：`create_image_api_base` 带 `/v1` 前缀时拼接错误
  - 控制：使用标准 URL 拼接，保证 `/p/...` 生成站点根路径下的 URL

## 预期结果
新增图片服务返回 `/p/img/...` 这类路径时，项目会自动补全并下载图片后发送；原有绝对 URL 与 `b64_json` 生图能力保持可用。
