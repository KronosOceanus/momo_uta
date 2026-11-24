# HTTP 本地服务边界审计

> 范围：本地 HTTP 服务、CORS、认证、静态文件、音频 Range、POST 边界。
> P0/P1 已实现：关闭 CORS、启动 token、Origin/Host 校验、POST 类型/大小限制、
> 静态路径越界防护、Range 语义、字段类型校验。

## 0. 结论

```text
服务只监听 127.0.0.1：正确
现在有启动 token + Origin/Host 校验
CORS 已移除
静态路径越界已防护
Range 语义已修正
```

剩余风险集中在高成本接口和限流。

## 1. 服务监听

```python
ThreadingHTTPServer(("127.0.0.1", port), H)
```

局域网不能直接访问，这点没问题。

但 `127.0.0.1` 不隔离浏览器：

```text
用户浏览任意网页
→ 网页请求 http://127.0.0.1:8766
→ 服务认为它是本地请求
```

## 2. CORS 全域开放

所有响应统一带：

```python
Access-Control-Allow-Origin: *
```

包括：

```text
/api/pl
/api/library
/api/song/<uid>
/audio/<uid>
/api/wave/<uid>
/static/*
```

后果：

```text
任意网站可以读取本机歌单
任意网站可以读取曲库标题/歌手
任意网站可以读取歌词
有 uid 时可以取音频流
```

## 3. 无认证

服务没有：

```text
启动 token
session
Origin 校验
Host 校验
CSRF 防护
```

任何能访问 localhost 的页面都可以调用接口。

## 4. 简单 POST 可以绕过 preflight

服务没有处理 OPTIONS，但 POST 也不检查 Content-Type。

因此恶意页面可以用简单请求：

```text
Content-Type: text/plain
body: JSON
```

服务仍会 `json.loads`，可能触发：

```text
/api/pl 清空/删除歌单
/api/lrc 保存歌词
/api/import/one 导入本地路径
/api/jobs 启动人声任务
```

即使跨域读取被浏览器限制，副作用已经发生。

## 5. Host / DNS rebinding

没有校验 `Host`。

理论上可被：

```text
恶意域名 → DNS 指向 127.0.0.1
```

再结合 CORS，扩大攻击面。

## 6. POST 大小与类型

当前：

```python
length = int(self.headers.get("Content-Length") or 0)
req = json.loads(self.rfile.read(length) or b"{}")
```

没有：

```text
最大 body 限制
Content-Type 校验
负数/异常 Content-Length 处理
请求字段白名单
```

本地恶意页面可以发超大 body，造成内存/CPU 压力。

## 7. 高成本接口

没有认证时，这些接口可以被反复触发：

```text
/api/wave/<uid>   波形计算
/api/jobs         人声任务
/api/import/one   本地文件导入
```

属于本地资源消耗和隐私风险。

## 8. Range 解析边界

`audio_info`：

```python
a, _, b = rng[6:].partition("-")
start = int(a) if a else 0
end = int(b) if b else size - 1
```

问题：

```text
bytes=-500     标准语义是最后 500 字节
                当前变成 0-500

bytes=100-50   start > end
                返回 0 长度和非法 Content-Range

start >= size  没有钳制
```

普通播放可能不受影响，但前缀 Range 和异常 Range 不可靠。

## 9. 静态文件

`static_file` 做了：

```text
必须以 /static/ 进入
拒绝 rel 中包含 ..
```

路径穿越基本被封住。

仍建议：

```text
resolve 后确认仍在 STATIC 目录下
禁止符号链接逃逸
```

## 10. 建议优先级

```text
P0  ✅ CORS 已移除；已加入启动随机 token + Origin/Host 校验
P1  ✅ POST Content-Type / body 大小 / 字段类型已校验
P1  ✅ /audio、/api/wave、/api/jobs、/api/import/one 需要 token
P2  ✅ Range 语义修正
P2  ✅ 静态文件 resolve/符号链接越界防护
P2  ✅ wave single-flight、jobs 并发上限、import 路径/扫描上限
P2  ✅ 安全响应头 + CSP nonce（保留 unsafe-eval 供 pywebview）
```

## 11. 推荐方案

```text
1. 页面和 API 同源，不再需要 CORS
2. 每次启动生成随机 token
3. 页面 HTML 注入 token，前端 API 请求带 token
4. 校验 Origin / Host
5. POST 只接受 application/json
6. body 设置上限
7. OPTIONS 明确拒绝或按需实现
8. Range 按 HTTP 标准修正
```

测试基线：

```text
362 Python
46 前端
UI 冒烟通过
```

## 12. P2 复核

P2 已实现后，再扫一遍，剩几个边界。

### P2：jobs 并发上限检查不是原子的 — 已修复

现在检查与占位在 `JOBS.start` 的同一把锁内完成，
超过 `jobs.max_active` 返回 429。

### P2：LRC 嵌套字段类型还未校验 — 已修复

现在会检查 `lines` / `rows` 的元素对象和 `translations` 的值类型，
错误直接返回 400。

### P2：wave 没有 ffmpeg 超时 — 已修复

现在 `waveform.timeout_s`（默认 60 秒）会 kill 卡住的 ffmpeg，
释放 single-flight 锁并返回错误。

### P3：目录扫描上限只统计音频/歌词 — 已修复

现在按总扫描条目计数，超过 5000 立即停止。

### P3：Range 单位大小写 — 已修复

`bytes=` 现在区分大小写。

HTTP Range 单位应大小写不敏感：

```text
Bytes=0-1
```

目前会落成 416。正常浏览器都发小写，影响很小。

### 已通过

```text
362 Python
46 前端
UI 冒烟通过
```

## 13. HTTP 再复核

P0/P1/P2 已修完，主链路通过。剩几个低优先级一致性边界。

### P3：/audio 返回没有走安全响应头 — 已修复

`_get_audio` 手动 `send_response`，只设置：

```text
Content-Type
Accept-Ranges
Content-Length
Content-Range
```

没有：

```text
X-Content-Type-Options
Referrer-Policy
X-Frame-Options
Cross-Origin-Resource-Policy
Cache-Control
```

现在音频响应也使用同一组安全响应头。

### P3：jobs 上限没有把 canceling 计入 — 已修复

`JOBS.start` 上限只统计：

```text
queued
running
```

正在取消的任务：

```text
canceling
```

现在 queued/running/canceling 都计入活动任务。

### P3：token 仍允许 query 兜底 — 已修复

`_token_ok` 支持：

```text
X-Momo-Token
?token=...
```

当前前端全部用 header，query 只是兜底。

query token 可能进入：

```text
浏览器历史
Referer
日志
```

现在只接受 X-Momo-Token header，query token 返回 403。

### P3：请求读取没有超时 — 已修复

本地服务没有 socket 超时。恶意/异常客户端可慢慢发送 body：

```text
Content-Length 合法
只发一点
连接长期占用
```

现在 handler socket timeout=15 秒，读取超时返回 408。

### 当前测试

```text
362 Python
46 前端
UI 冒烟通过
```
