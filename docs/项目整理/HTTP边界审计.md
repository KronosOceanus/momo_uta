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
356 Python
46 前端
UI 冒烟通过
```
