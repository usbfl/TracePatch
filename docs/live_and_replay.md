# Live / Replay

交付构建没有实际模型请求。默认 provider=offline；发现环境变量中的 key 也不会自动启用网络。

只替换叶字段提取器。模型只看到已经付费读取的原文、字段与类型、来源/版本和作用域。输出 JSON 包含 `outcome`（KNOWN/UNKNOWN）、`value`、`source_id`、`source_version`、`quote`、`reason`。精确引文定位只提供可追溯性，不证明语义提取正确。非法 JSON/类型/引用返回 UNKNOWN，不循环修格式。

## 手动启用一次接口 smoke

PowerShell：

```powershell
$env:TRACEPATCH_API_KEY = "在本机填写你的密钥"
$env:TRACEPATCH_BASE_URL = "你的兼容服务地址，通常以 /v1 结束"
$env:TRACEPATCH_MODEL = "你服务中的模型标识"
python -m tracepatch data build --config configs/live_smoke.yaml --out data/live_smoke_local
python -m tracepatch run --config configs/live_smoke.yaml --data data/live_smoke_local --split dev --out runs/live_smoke_local --provider live --allow-network
python -m tracepatch evaluate --run runs/live_smoke_local --gold data/live_smoke_local/evaluation
python -m tracepatch report --run runs/live_smoke_local
```

Bash：

```bash
export TRACEPATCH_API_KEY='在本机填写你的密钥'
export TRACEPATCH_BASE_URL='你的兼容服务 /v1 地址'
export TRACEPATCH_MODEL='你的模型标识'
# 随后执行上述相同 python 命令；必要时替换为 python3。
```

这只跑 2 个 dev 场景 × 1 个缺边条件 × 1 个预算 × graph_only/tracepatch，共 4 个接口检查运行；整个矩阵最多 32 个 API 尝试。不能将其当作正式五方法比较。脚本不自动加载 `.env`；必须在当前终端设置环境变量。`.env.example` 只有空值。

接口为标准库 urllib 的 `POST {base_url}/chat/completions`。HTTP 重定向被拒绝。仅 429/5xx 自动重试一次；网络超时/连接结果不明保守记 uncertain，不自动重发，避免潜在重复收费。其他 4xx 不重试。请求上限先经独立 SQLite 账本预留。默认 timeout=20 秒，max_input_chars=12000，max_context_chars=16000，max_output_tokens=256，temperature=0；可在配置 `model` 对象修改。base_url/model 由显式环境变量覆盖。默认不配置价格，不估算金额；响应无 usage 时 token 标记 unknown。

同一 live 运行恢复需再明确 `--allow-network`，已发送但未确认的请求不会重发。不要更换源码、证据或模型参数后复用旧日志。

## 重放真实记录

```bash
python -m tracepatch freeze-protocol --run runs/live_smoke_local --out protocols/live_local.lock.json
python -m tracepatch run --protocol protocols/live_local.lock.json --data data/live_smoke_local --split dev --out runs/replay_local --provider replay --replay-from runs/live_smoke_local
python -m tracepatch evaluate --run runs/replay_local --gold data/live_smoke_local/evaluation
python -m tracepatch report --run runs/replay_local
```

源运行必须是通过冻结状态/动作/配置哈希检查的 live 运行，原始模型参数、源运行 ID、请求哈希、证据哈希、规则与提示词版本都保留。更换输出目录或 live→replay 不改变语义哈希；更换证据、模型/参数或提示词会拒绝命中。不能对未录制的 test 场景凭空重放。重放没有真实网络请求，实际调用计数为 0，来源模型使用情况保留于记录。

测试中的模拟 HTTP 响应只用于测试，未伪装成真实模型记录，未附带“真实模型效果”报告。
