# BUG 记录

> 记录已确认或高度可疑、**尚未修复**的问题。
> 修复后从本文移除，具体回归以 tests / git log 为准。
>
> 相关：[优化记录](优化.md) · [架构](architecture.md) · [nhlrc](topics/nhlrc.md)

## 1. wheel 缺少默认配置和前端静态资源

- 编号：BUG-001
- 状态：⬜ 待修
- 优先级：中
- 影响：`pip install` 后命令入口运行时报错
- 复现：离线 wheel 安装检查已确认
- 范围：wheel，不代表 macOS `.app` 构建

### 现象

普通非 editable 安装生成 `nihonco-uta` 命令，但运行时找不到：

```text
config/defaults.json
前端 static 资源
```

### 原因

`pyproject.toml` 只配置了：

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

没有把非 Python 数据文件打进 wheel。

### 方向

```text
1. 补充 package-data / include-package-data
2. 确认 config/defaults.json 和静态资源进入 wheel
3. 用干净虚拟环境做一次非 editable 安装检查
```

```text
不要用 .app 能运行来证明 wheel 没问题。
```

### 相关

```text
pyproject.toml
```

## 修复顺序建议

```text
BUG-001 wheel 资源
```

## 说明

```text
1. 本文只记录未修复问题。
2. 修复并补回归测试后，从本文删除。
3. 记录中的「君 → you」「空 → sky」是测试 fixture，不是应用自带歌词或读音。
```
